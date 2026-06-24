import importlib
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


eval_context_rag = importlib.import_module("eval.eval_context_rag")


class _FakeGoldQdrant:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    async def scroll(self, **kwargs):
        condition = kwargs["scroll_filter"].must[0]
        value = getattr(condition.match, "value", None)
        self.calls.append((kwargs["collection_name"], condition.key, value))
        payload = self.responses.get((condition.key, value))
        if payload is None:
            return [], None
        return [SimpleNamespace(payload=payload)], None


class _FakeMysqlSession:
    def __init__(self, found_ids=None):
        self.found_ids = {int(value) for value in (found_ids or [])}

    async def execute(self, _statement, params):
        found = int(params["news_id"]) in self.found_ids

        class _Result:
            def __init__(self, has_row):
                self.has_row = has_row

            def first(self):
                return (1,) if self.has_row else None

        return _Result(found)


class _FakeEvalTraceSession:
    def __init__(self):
        self.executed = []
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, statement, params=None):
        self.executed.append((str(statement), params or {}))

    async def commit(self):
        self.committed = True


class ContextRagEvalTests(unittest.TestCase):
    def test_extract_citations_supports_scoped_news_ids(self):
        citations = eval_context_rag.extract_citations(
            "参考 [news:jjrb:abc123] 和 [news:2726]，无效 [web:x] 忽略。"
        )

        self.assertEqual(citations, ["news:jjrb:abc123", "news:2726"])

    def test_metric_summary_computes_recall_mrr_and_route_accuracy(self):
        rows = [
            {
                "gold_evidence_ids": ["news:a", "news:b"],
                "retrieved_evidence_ids": ["news:x", "news:b", "news:a"],
                "should_answer": True,
                "should_refuse": False,
                "expected_route": "econ_finance_query",
                "route": "econ_finance_query",
                "latency_ms": 100,
            },
            {
                "gold_evidence_ids": [],
                "retrieved_evidence_ids": ["news:z"],
                "should_answer": False,
                "should_refuse": True,
                "expected_route": "econ_finance_query",
                "route": "default",
                "answer": "站内未找到可靠新闻证据，建议换个关键词再试。",
                "citations": [],
                "validation": {"passed": True, "hallucinationRisk": "low"},
                "latency_ms": 300,
            },
        ]

        metrics = eval_context_rag.compute_metrics(rows, top_k=5)

        self.assertAlmostEqual(metrics["Recall@5"], 1.0)
        self.assertAlmostEqual(metrics["MRR"], 0.5)
        self.assertAlmostEqual(metrics["EvidenceRecall@5"], 1.0)
        self.assertAlmostEqual(metrics["RouteAccuracy"], 0.5)
        self.assertAlmostEqual(metrics["NoAnswerAccuracy"], 1.0)
        self.assertAlmostEqual(metrics["ValidationPassRate"], 1.0)

    def test_b_v3_metrics_include_confirmation_and_long_context_fields(self):
        rows = [{
            "should_answer": True,
            "gold_evidence_ids": ["news:jjrb:1"],
            "retrieved_evidence_ids": ["news:jjrb:1"],
            "anchor_resolution": {
                "requires_user_confirmation": True,
                "answered_without_confirmation": False,
            },
            "long_context": {
                "topic_recall_at_100": True,
                "anchor_recall_at_100": True,
            },
            "memory_source_separated": True,
        }]

        metrics = eval_context_rag.compute_metrics(rows)

        self.assertIn("ConfirmationRequiredAccuracy", metrics)
        self.assertIn("OverconfidentAnswerRate", metrics)
        self.assertIn("LongContextTopicRecall@100", metrics)
        self.assertIn("LongContextAnchorRecall@100", metrics)
        self.assertIn("MemorySourceSeparationRate", metrics)
        self.assertEqual(metrics["ConfirmationRequiredAccuracy"], 1.0)
        self.assertEqual(metrics["OverconfidentAnswerRate"], 0.0)

    def test_memory_recall_answer_mode_does_not_require_factual_evidence_recall(self):
        rows = [{
            "id": "b_v3_memory_only",
            "should_answer": True,
            "answer_mode": "memory_recall_not_fact_evidence",
            "gold_evidence_ids": ["news:jjrb:anchor"],
            "retrieved_evidence_ids": [],
            "answer": "根据会话记忆，最初主题是经济日报的新质生产力报道。",
            "validation": {"passed": True, "hallucinationRisk": "low"},
            "long_context": {
                "topic_recall_at_100": True,
                "anchor_recall_at_100": True,
            },
            "memory_source_separated": True,
        }]

        metrics = eval_context_rag.compute_metrics(rows)
        failures = eval_context_rag.failed_cases(rows)
        diagnostics = eval_context_rag.diagnose_failures(rows)

        self.assertEqual(metrics["answerable_gold_cases"], 0)
        self.assertIsNone(metrics["Recall@5"])
        self.assertEqual(failures, [])
        self.assertEqual(diagnostics, [])

    def test_b_v3_metrics_include_source_policy_ocr_and_carryover_fields(self):
        rows = [
            {
                "source_label": {"expected": "ocr_screenshot", "actual": "ocr_screenshot"},
                "anchor_resolution": {
                    "warning_required": True,
                    "external_tool_expected": "web_search",
                },
                "answer": "注意：这条信息来自 X，可信度较低；以下只能作为线索分析，不作为确定事实。",
                "tool_calls": [{"name": "web_search"}],
                "ocr_trace": {
                    "source_url": "https://x.example/post/1",
                    "image_path": "captures/x.png",
                    "raw_image_hash": "sha256:abc",
                    "captured_at": "2026-06-24T12:00:00Z",
                    "ocr_confidence": 0.86,
                },
                "confirmed_carryover": {
                    "expected_anchor_id": "news:jjrb:1",
                    "actual_anchor_id": "news:jjrb:1",
                },
                "insufficient_evidence_expected": True,
                "insufficient_evidence_handled": True,
            },
            {
                "source_label": {"expected": "web_search", "actual": "rag"},
                "anchor_resolution": {
                    "warning_required": True,
                    "external_tool_expected": "web_search",
                },
                "tool_calls": [{"name": "retrieve_news"}],
                "ocr_trace": {
                    "source_url": "https://x.example/post/2",
                    "image_path": "captures/x2.png",
                },
                "confirmed_carryover": {
                    "expected_anchor_id": "news:jjrb:1",
                    "actual_anchor_id": "news:jjrb:2",
                },
                "insufficient_evidence_expected": True,
                "answer": "没有找到可靠新闻证据。",
            },
        ]

        metrics = eval_context_rag.compute_metrics(rows)

        self.assertEqual(metrics["SourceLabelAccuracy"], 0.5)
        self.assertEqual(metrics["LowCredibilityWarningRate"], 0.5)
        self.assertEqual(metrics["ExternalFallbackTriggerAccuracy"], 0.5)
        self.assertEqual(metrics["OCRTraceCompleteness"], 0.5)
        self.assertEqual(metrics["ConfirmedCarryoverAccuracy"], 0.5)
        self.assertEqual(metrics["InsufficientEvidenceCorrectness"], 1.0)

    def test_b_v3_extended_metrics_render_in_markdown_report(self):
        metrics = {
            "SourceLabelAccuracy": 1.0,
            "LowCredibilityWarningRate": 1.0,
            "ExternalFallbackTriggerAccuracy": 1.0,
            "OCRTraceCompleteness": 1.0,
            "ConfirmedCarryoverAccuracy": 1.0,
            "InsufficientEvidenceCorrectness": 1.0,
        }

        markdown = eval_context_rag.render_markdown_report(
            mode="full-e2e",
            cases=[],
            rows=[],
            metrics=metrics,
            failures=[],
        )

        self.assertIn("SourceLabelAccuracy", markdown)
        self.assertIn("LowCredibilityWarningRate", markdown)
        self.assertIn("ExternalFallbackTriggerAccuracy", markdown)
        self.assertIn("OCRTraceCompleteness", markdown)
        self.assertIn("ConfirmedCarryoverAccuracy", markdown)
        self.assertIn("InsufficientEvidenceCorrectness", markdown)

        sampled_markdown = eval_context_rag.render_sampled_full_e2e_report(
            cases=[],
            rows=[],
            metrics=metrics,
            failures=[],
        )

        self.assertIn("SourceLabelAccuracy", sampled_markdown)
        self.assertIn("LowCredibilityWarningRate", sampled_markdown)
        self.assertIn("ExternalFallbackTriggerAccuracy", sampled_markdown)
        self.assertIn("OCRTraceCompleteness", sampled_markdown)
        self.assertIn("ConfirmedCarryoverAccuracy", sampled_markdown)
        self.assertIn("InsufficientEvidenceCorrectness", sampled_markdown)

    def test_load_gold_cases_validates_required_fields(self):
        cases = eval_context_rag.load_gold_cases("eval/gold/eval_gold_retrieval.jsonl")

        self.assertEqual(len(cases), 50)
        required = {
            "id",
            "expected_route",
            "gold_evidence_ids",
            "should_answer",
            "should_refuse",
            "must_have_citations",
            "case_type",
            "notes",
        }
        for case in cases:
            self.assertTrue(required.issubset(case.keys()))
            self.assertTrue("question" in case or "turns" in case)

    def test_b_v3_gold_suite_covers_required_full_e2e_paths(self):
        cases = eval_context_rag.load_gold_cases(eval_context_rag.B_V3_GOLD_PATH)

        coverage = eval_context_rag.summarize_b_v3_gold_coverage(cases)

        self.assertGreaterEqual(len(cases), 6)
        self.assertEqual(coverage["missing_required_scenarios"], [])
        for scenario in eval_context_rag.B_V3_REQUIRED_SCENARIOS:
            self.assertGreaterEqual(coverage["scenario_counts"].get(scenario, 0), 1, scenario)
        for case in cases:
            self.assertEqual(case.get("eval_profile"), "b_v3_anchor_resolver")
            self.assertIn("b_v3_scenario", case)
            self.assertIn("anchor_resolution", case)

    def test_b_v3_long_context_gold_case_expands_to_round_100_turns(self):
        cases = eval_context_rag.load_gold_cases(eval_context_rag.B_V3_GOLD_PATH)
        case = next(item for item in cases if item["b_v3_scenario"] == "long_context_100")

        turns = eval_context_rag._case_turns(case)

        self.assertEqual(len(turns), 100)
        self.assertIn("第一轮", turns[0])
        self.assertIn("第100轮", turns[-1])

    def test_gold_rank_diagnosis_distinguishes_top20_and_route_buckets(self):
        row = {
            "id": "exact_econ_999",
            "case_type": "A_exact_news_qa",
            "expected_route": "econ_finance_query",
            "route": "econ_finance_query",
            "gold_evidence_ids": ["news:gold"],
            "retrieved_evidence_ids": [f"news:x{index}" for index in range(6)] + ["news:gold"],
            "should_answer": True,
            "should_refuse": False,
        }

        diagnosis = eval_context_rag.diagnose_failure(row, metric_k=5, diagnosis_k=20)

        self.assertEqual(diagnosis["gold_ranks"], {"news:gold": 7})
        self.assertIn("gold_in_top20_not_top5", diagnosis["buckets"])

        route_row = dict(row)
        route_row.update({
            "id": "investment_999",
            "case_type": "H_investment_boundary",
            "route": "recommendation",
            "gold_evidence_ids": [],
            "retrieved_evidence_ids": [],
            "should_answer": False,
            "should_refuse": True,
        })

        route_diagnosis = eval_context_rag.diagnose_failure(route_row, metric_k=5, diagnosis_k=20)

        self.assertIn("route_mismatch", route_diagnosis["buckets"])
        self.assertIn("investment_boundary_route_error", route_diagnosis["buckets"])

    def test_gold_existence_diagnosis_marks_existing_gold_as_query_or_ranking_issue(self):
        row = {
            "id": "context_follow_999",
            "case_type": "B_context_follow_up",
            "expected_route": "econ_finance_query",
            "route": "econ_finance_query",
            "gold_evidence_ids": ["news:jjrb:exists"],
            "retrieved_evidence_ids": [f"news:x{index}" for index in range(20)],
            "should_answer": True,
            "should_refuse": False,
        }
        presence = {
            "news:jjrb:exists": {
                "evidence_id": "news:jjrb:exists",
                "exists": True,
                "status": "exists",
                "present_in": ["qdrant_payload"],
            }
        }

        diagnosis = eval_context_rag.diagnose_failure(
            row,
            metric_k=5,
            diagnosis_k=20,
            gold_existence=presence,
        )

        self.assertIn("gold_not_in_top20", diagnosis["buckets"])
        self.assertIn("query_rewrite_or_ranking", diagnosis["buckets"])
        self.assertNotIn("corpus_missing", diagnosis["buckets"])
        self.assertEqual(diagnosis["gold_existence"]["news:jjrb:exists"]["present_in"], ["qdrant_payload"])

    def test_gold_existence_diagnosis_marks_missing_gold_as_corpus_missing(self):
        row = {
            "id": "source_999",
            "case_type": "D_source_limited",
            "expected_route": "econ_finance_query",
            "route": "econ_finance_query",
            "gold_evidence_ids": ["news:jjrb:missing"],
            "retrieved_evidence_ids": [f"news:x{index}" for index in range(20)],
            "should_answer": True,
            "should_refuse": False,
        }
        presence = {
            "news:jjrb:missing": {
                "evidence_id": "news:jjrb:missing",
                "exists": False,
                "status": "corpus_missing",
                "present_in": [],
            }
        }

        diagnosis = eval_context_rag.diagnose_failure(
            row,
            metric_k=5,
            diagnosis_k=20,
            gold_existence=presence,
        )

        self.assertIn("gold_not_in_top20", diagnosis["buckets"])
        self.assertIn("corpus_missing", diagnosis["buckets"])
        self.assertNotIn("query_rewrite_or_ranking", diagnosis["buckets"])

    def test_gold_existence_summary_aggregates_sources(self):
        diagnostics = [
            {
                "id": "a",
                "buckets": ["gold_not_in_top20"],
                "gold_existence": {
                    "news:jjrb:a": {"exists": True, "status": "exists", "present_in": ["qdrant_payload"]},
                    "news:jjrb:b": {"exists": False, "status": "corpus_missing", "present_in": []},
                },
            },
            {
                "id": "b",
                "buckets": ["gold_not_in_top20"],
                "gold_existence": {
                    "news:2726": {"exists": True, "status": "exists", "present_in": ["mysql_metadata", "news_chunk"]},
                },
            },
        ]

        summary = eval_context_rag.summarize_gold_existence(diagnostics)

        self.assertEqual(summary["gold_refs_checked"], 3)
        self.assertEqual(summary["exists"], 2)
        self.assertEqual(summary["missing"], 1)
        self.assertEqual(summary["source_hits"]["qdrant_payload"], 1)
        self.assertEqual(summary["source_hits"]["mysql_metadata"], 1)

    def test_check_gold_evidence_existence_checks_mysql_jsonl_and_qdrant(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "econ.jsonl"
            jsonl_path.write_text(
                json.dumps(
                    {
                        "evidence_id": "news:jjrb:jsonl",
                        "doc_id": "jjrb:jsonl",
                        "title": "jsonl parent",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            fake_qdrant = _FakeGoldQdrant({
                ("evidence_id", "news:jjrb:qdrant"): {
                    "evidence_id": "news:jjrb:qdrant",
                    "title": "qdrant chunk",
                }
            })

            results = asyncio.run(
                eval_context_rag.check_gold_evidence_existence(
                    ["news:2726", "news:jjrb:jsonl", "news:jjrb:qdrant", "news:jjrb:missing"],
                    db=_FakeMysqlSession(found_ids=[2726]),
                    qdrant_factory=lambda: fake_qdrant,
                    collections=["toutiao_econ_chunks_candidate_20260621"],
                    jsonl_paths=[jsonl_path],
                )
            )

        self.assertTrue(results["news:2726"]["checks"]["mysql_metadata"]["found"])
        self.assertIn("mysql_metadata", results["news:2726"]["present_in"])
        self.assertIn("news_chunk", results["news:jjrb:jsonl"]["present_in"])
        self.assertIn("qdrant_payload", results["news:jjrb:qdrant"]["present_in"])
        self.assertEqual(results["news:jjrb:missing"]["status"], "corpus_missing")

    def test_mysql_eval_trace_excludes_session_memory_fields(self):
        fake_session = _FakeEvalTraceSession()
        original_session_local = eval_context_rag.AsyncSessionLocal
        eval_context_rag.AsyncSessionLocal = lambda: fake_session
        try:
            asyncio.run(
                eval_context_rag.persist_eval_trace_to_mysql(
                    rows=[
                        {
                            "id": "case_a",
                            "case_type": "B_context_follow_up",
                            "mode": "retrieve-only",
                            "route": "econ_finance_query",
                            "expected_route": "econ_finance_query",
                            "retrieval_query": "新质生产力 制造业",
                            "retrieved_evidence_ids": ["news:jjrb:a"],
                            "gold_evidence_ids": ["news:jjrb:b"],
                            "context": {"session_summary": "not factual evidence"},
                        }
                    ],
                    diagnostics=[
                        {
                            "id": "case_a",
                            "buckets": ["gold_not_in_top20", "query_rewrite_or_ranking"],
                            "gold_existence": {"news:jjrb:b": {"exists": True}},
                        }
                    ],
                    metrics={"Recall@5": 0.0},
                    run_id="unit-test-run",
                )
            )
        finally:
            eval_context_rag.AsyncSessionLocal = original_session_local

        self.assertTrue(fake_session.committed)
        insert_params = [params for _sql, params in fake_session.executed if params.get("case_id") == "case_a"][0]
        serialized = json.dumps(insert_params, ensure_ascii=False)
        self.assertIn("news:jjrb:a", serialized)
        self.assertNotIn("session_summary", serialized)
        self.assertNotIn("not factual evidence", serialized)

    def test_case_id_selection_preserves_requested_order(self):
        cases = [
            {"id": "a", "question": "A", "expected_route": "default", "gold_evidence_ids": [],
             "should_answer": False, "should_refuse": True, "must_have_citations": False, "case_type": "x", "notes": ""},
            {"id": "b", "question": "B", "expected_route": "default", "gold_evidence_ids": [],
             "should_answer": False, "should_refuse": True, "must_have_citations": False, "case_type": "x", "notes": ""},
        ]

        selected = eval_context_rag.select_cases(cases, case_ids=["b", "a"], case_limit=0)

        self.assertEqual([case["id"] for case in selected], ["b", "a"])

    def test_light_rule_rerank_promotes_title_entity_overlap(self):
        parents = [
            {"id": "wrong", "title": "新质生产力相关观察", "summary": ""},
            {"id": "gold", "title": "在发展新质生产力上走在前列", "summary": ""},
        ]

        reranked = eval_context_rag.light_rule_rerank(
            "发展新质生产力上走在前列这篇报道讲了什么？",
            parents,
        )

        self.assertEqual(reranked[0]["id"], "gold")

    def test_light_rule_rerank_promotes_source_match_for_source_limited_query(self):
        parents = [
            {"id": "rmrb1", "title": "新质生产力观察", "summary": "", "source": "rmrb"},
            {"id": "jjrb1", "title": "新质生产力与制造业", "summary": "", "source": "jjrb"},
        ]

        reranked = eval_context_rag.light_rule_rerank(
            "只看经济日报，新质生产力如何影响制造业？",
            parents,
        )

        self.assertEqual(reranked[0]["id"], "jjrb1")

    def test_light_rule_rerank_recognizes_industrial_chain_entity(self):
        parents = [
            {"id": "nochain", "title": "科技创新观察", "summary": ""},
            {"id": "chain", "title": "新质生产力对产业链的影响", "summary": ""},
        ]

        reranked = eval_context_rag.light_rule_rerank(
            "新质生产力对制造业、产业链、科技创新分别有什么影响？",
            parents,
        )

        self.assertEqual(reranked[0]["id"], "chain")

    def test_full_e2e_records_timeout_row_and_continues(self):
        original_auth = eval_context_rag._ensure_auth
        original_chat = eval_context_rag._chat_sse
        calls = []

        eval_context_rag._ensure_auth = lambda _host, _port: eval_context_rag.ApiAuth("u", "p", "token")

        def fake_chat(_host, _port, _token, message, _session_id, **_kwargs):
            calls.append(message)
            if message == "timeout":
                raise TimeoutError("simulated")
            return {"answer": "ok", "done": {"sessionId": 7, "evidence": [], "validation": {"passed": True}}}

        eval_context_rag._chat_sse = fake_chat
        try:
            rows = eval_context_rag.evaluate_full_e2e([
                {"id": "a", "question": "timeout", "expected_route": "default", "gold_evidence_ids": [],
                 "should_answer": False, "should_refuse": True, "must_have_citations": False, "case_type": "x", "notes": ""},
                {"id": "b", "question": "ok", "expected_route": "default", "gold_evidence_ids": [],
                 "should_answer": True, "should_refuse": False, "must_have_citations": False, "case_type": "x", "notes": ""},
            ], host="127.0.0.1", port=8030)
        finally:
            eval_context_rag._ensure_auth = original_auth
            eval_context_rag._chat_sse = original_chat

        self.assertEqual(calls, ["timeout", "ok"])
        self.assertEqual(rows[0]["error"], "simulated")
        self.assertEqual(rows[1]["answer"], "ok")
        self.assertEqual(rows[1]["done"]["sessionId"], 7)

        metrics = eval_context_rag.compute_sampled_full_e2e_metrics(rows)

        self.assertEqual(metrics["timeout_rate"], 0.5)
        self.assertEqual(metrics["sse_done_received"], 0.5)

    def test_full_e2e_enriches_b_v3_confirmed_carryover_metrics(self):
        original_auth = eval_context_rag._ensure_auth
        original_chat = eval_context_rag._chat_sse

        eval_context_rag._ensure_auth = lambda _host, _port: eval_context_rag.ApiAuth("u", "p", "token")

        def fake_chat(_host, _port, _token, _message, _session_id, **_kwargs):
            return {
                "answer": "基于已确认报道解释。[news:jjrb:anchor]",
                "done": {
                    "sessionId": 7,
                    "evidence": ["news:jjrb:anchor"],
                    "validation": {"passed": True, "hallucinationRisk": "low"},
                },
                "has_reasoning_leak": False,
            }

        eval_context_rag._chat_sse = fake_chat
        try:
            rows = eval_context_rag.evaluate_full_e2e([{
                "id": "b_v3_confirmed_followup_unit",
                "turns": ["帮我找那篇新闻。", "就是第一篇，请按这篇解释。"],
                "expected_route": "econ_finance_query",
                "gold_evidence_ids": ["news:jjrb:anchor"],
                "should_answer": True,
                "should_refuse": False,
                "must_have_citations": True,
                "case_type": "Bv3_confirmed_followup",
                "notes": "",
                "eval_profile": "b_v3_anchor_resolver",
                "b_v3_scenario": "confirmed_followup",
                "anchor_resolution": {
                    "expected_state": "ANCHOR_CONFIRMED",
                    "requires_user_confirmation": False,
                    "answered_without_confirmation": False,
                    "confirmed_anchor_expected": True,
                },
            }], host="127.0.0.1", port=8030)
        finally:
            eval_context_rag._ensure_auth = original_auth
            eval_context_rag._chat_sse = original_chat

        self.assertEqual(rows[0]["confirmed_carryover"]["expected_anchor_id"], "news:jjrb:anchor")
        self.assertEqual(rows[0]["confirmed_carryover"]["actual_anchor_id"], "news:jjrb:anchor")
        metrics = eval_context_rag.compute_metrics(rows)
        self.assertEqual(metrics["ConfirmedCarryoverAccuracy"], 1.0)

    def test_external_fallback_metric_infers_web_search_from_answer_text_without_tool_trace(self):
        metrics = eval_context_rag.compute_metrics([{
            "anchor_resolution": {"external_tool_expected": "web_search"},
            "answer": "未配置 WEB_SEARCH_API_KEY，联网搜索暂不可用；需要站外工具。",
        }])

        self.assertEqual(metrics["ExternalFallbackTriggerAccuracy"], 1.0)

    def test_full_e2e_promotes_done_anchor_metadata_to_row(self):
        original_auth = eval_context_rag._ensure_auth
        original_chat = eval_context_rag._chat_sse

        eval_context_rag._ensure_auth = lambda _host, _port: eval_context_rag.ApiAuth("u", "p", "token")

        def fake_chat(_host, _port, _token, _message, _session_id, **_kwargs):
            return {
                "answer": "请确认是哪一篇。",
                "done": {
                    "sessionId": 7,
                    "evidence": [],
                    "anchorResolution": {
                        "state": "WAITING_USER_CONFIRMATION",
                        "requires_user_confirmation": True,
                    },
                    "confirmedAnchor": {
                        "anchor_id": "news:jjrb:anchor",
                    },
                },
                "has_reasoning_leak": False,
            }

        eval_context_rag._chat_sse = fake_chat
        try:
            rows = eval_context_rag.evaluate_full_e2e([{
                "id": "b_v3_done_metadata_unit",
                "question": "我记得经济日报那篇新闻是哪篇？",
                "expected_route": "econ_finance_query",
                "gold_evidence_ids": [],
                "should_answer": False,
                "should_refuse": False,
                "must_have_citations": False,
                "case_type": "Bv3_candidate_confirmation",
                "notes": "",
                "eval_profile": "b_v3_anchor_resolver",
                "b_v3_scenario": "candidate_confirmation",
            }], host="127.0.0.1", port=8030)
        finally:
            eval_context_rag._ensure_auth = original_auth
            eval_context_rag._chat_sse = original_chat

        self.assertEqual(rows[0]["anchor_resolution"]["state"], "WAITING_USER_CONFIRMATION")
        self.assertEqual(rows[0]["confirmed_anchor"]["anchor_id"], "news:jjrb:anchor")

    def test_b_v3_anchor_metrics_use_actual_done_state_not_gold_expectation(self):
        row = eval_context_rag._enrich_b_v3_eval_row({
            "id": "b_v3_actual_state_unit",
            "eval_profile": "b_v3_anchor_resolver",
            "b_v3_scenario": "candidate_confirmation",
            "anchor_resolution": {
                "expected_state": "WAITING_USER_CONFIRMATION",
                "requires_user_confirmation": True,
            },
            "done": {
                "anchorResolution": {
                    "state": "READY_TO_ANSWER",
                    "requires_user_confirmation": False,
                },
            },
        })

        self.assertEqual(row["anchor_resolution"]["expected_state"], "WAITING_USER_CONFIRMATION")
        self.assertEqual(row["anchor_resolution"]["actual_state"], "READY_TO_ANSWER")
        self.assertFalse(row["anchor_resolution"]["actual_requires_user_confirmation"])

        metrics = eval_context_rag.compute_metrics([row])

        self.assertEqual(metrics["ConfirmationRequiredAccuracy"], 0.0)

    def test_b_v3_source_label_uses_done_candidate_acquisition_method(self):
        row = eval_context_rag._enrich_b_v3_eval_row({
            "id": "b_v3_done_source_label_unit",
            "eval_profile": "b_v3_anchor_resolver",
            "b_v3_scenario": "ocr_lead",
            "anchor_resolution": {
                "acquisition_method": "web_search",
            },
            "done": {
                "anchorResolution": {
                    "state": "WAITING_USER_CONFIRMATION",
                    "requires_user_confirmation": True,
                    "candidates": [{
                        "anchor_id": "https://x.example/post/1",
                        "source_name": "X",
                        "source_url": "https://x.example/post/1",
                        "source_credibility": "low",
                        "verification_status": "unverified",
                        "acquisition_method": "ocr_screenshot",
                    }],
                },
            },
        })

        self.assertEqual(row["source_label"]["expected"], "web_search")
        self.assertEqual(row["source_label"]["actual"], "ocr_screenshot")

    def test_retrieve_once_can_use_v2_adapter(self):
        calls = []
        original_v2 = eval_context_rag.search_news_rag_v2
        original_rerank = eval_context_rag.rerank
        original_aggregate = eval_context_rag._aggregate_parents

        async def fake_v2(query, limit=50, **kwargs):
            calls.append((query, limit, kwargs.get("tool_name")))
            return {
                "items": [{"id": "jjrb:v2", "evidence_id": "news:jjrb:v2"}],
                "evidence_ids": ["news:jjrb:v2"],
                "collection_name": "news_chunks_v2",
                "collection_route": "econ_finance_query",
                "index_version": "v2_unified",
            }

        async def fake_rerank(_query, items, top_k=5):
            return items[:top_k]

        eval_context_rag.search_news_rag_v2 = fake_v2
        eval_context_rag.rerank = fake_rerank
        eval_context_rag._aggregate_parents = lambda ranked, top_k: ranked[:top_k]
        try:
            result = asyncio.run(
                eval_context_rag._retrieve_once("economy query", limit=5, top_k=5, use_v2=True)
            )
        finally:
            eval_context_rag.search_news_rag_v2 = original_v2
            eval_context_rag.rerank = original_rerank
            eval_context_rag._aggregate_parents = original_aggregate

        self.assertEqual(calls, [("economy query", 5, "retrieve_news")])
        self.assertEqual(result["collection"], "news_chunks_v2")
        self.assertEqual(result["index_version"], "v2_unified")
        self.assertEqual(result["retrieved_evidence_ids"], ["news:jjrb:v2"])

    def test_retrieve_once_can_use_api_reranker(self):
        calls = []
        original_v2 = eval_context_rag.search_news_rag_v2
        original_rerank = eval_context_rag.rerank
        original_api_rerank = eval_context_rag.api_rerank
        original_aggregate = eval_context_rag._aggregate_parents

        async def fake_v2(query, limit=50, **kwargs):
            calls.append(("v2", query, limit, kwargs.get("tool_name")))
            return {
                "items": [
                    {"id": "a", "evidence_id": "news:a", "title": "A", "summary": "first"},
                    {"id": "b", "evidence_id": "news:b", "title": "B", "summary": "second"},
                ],
                "evidence_ids": ["news:a", "news:b"],
                "collection_name": "news_chunks_v2",
                "collection_route": "econ_finance_query",
                "index_version": "v2_unified",
            }

        async def fake_api_rerank(query, items, top_k=5, **kwargs):
            calls.append(("api_rerank", query, top_k, kwargs.get("model")))
            ranked = [dict(items[1], rerank_score=0.91), dict(items[0], rerank_score=0.42)]
            return ranked[:top_k], {"used": True, "reranker_used": "siliconflow_api", "api_calls": 1}

        async def fail_local_rerank(_query, _items, top_k=5):
            raise AssertionError("local rerank should not be called")

        eval_context_rag.search_news_rag_v2 = fake_v2
        eval_context_rag.api_rerank = fake_api_rerank
        eval_context_rag.rerank = fail_local_rerank
        eval_context_rag._aggregate_parents = lambda ranked, top_k: ranked[:top_k]
        try:
            result = asyncio.run(
                eval_context_rag._retrieve_once(
                    "economy query",
                    limit=5,
                    top_k=5,
                    use_v2=True,
                    use_api_rerank=True,
                    api_rerank_model="Pro/BAAI/bge-reranker-v2-m3",
                )
            )
        finally:
            eval_context_rag.search_news_rag_v2 = original_v2
            eval_context_rag.api_rerank = original_api_rerank
            eval_context_rag.rerank = original_rerank
            eval_context_rag._aggregate_parents = original_aggregate

        self.assertEqual(calls[0], ("v2", "economy query", 5, "retrieve_news"))
        self.assertEqual(calls[1], ("api_rerank", "economy query", 2, "Pro/BAAI/bge-reranker-v2-m3"))
        self.assertEqual(result["retrieved_evidence_ids"], ["news:b", "news:a"])
        self.assertEqual(result["reranker_used"], "siliconflow_api")
        self.assertTrue(result["reranker_meta"]["used"])

    def test_v2_context_follow_passes_clean_query_and_expanded_vector_query(self):
        calls = []
        original_retrieve_once = eval_context_rag._retrieve_once

        async def fake_retrieve_once(query, limit, top_k, **kwargs):
            calls.append({
                "query": query,
                "vector_query": kwargs.get("vector_query"),
                "use_v2": kwargs.get("use_v2"),
            })
            return {
                "route": "econ_finance_query",
                "rag_route": None,
                "retrieved_evidence_ids": ["news:jjrb:v2"],
                "raw_evidence_ids": ["news:jjrb:v2"],
                "latency_ms": 1.0,
                "collection": "news_chunks_v2",
                "index_version": "v2_unified",
                "items_count": 1,
            }

        eval_context_rag._retrieve_once = fake_retrieve_once
        try:
            rows = asyncio.run(eval_context_rag.evaluate_retrieve_only([
                {
                    "id": "context_follow_x",
                    "turns": [
                        "最近高质量发展和新质生产力有什么新闻？",
                        "那它对制造业有什么影响？简单说，带引用。",
                    ],
                    "expected_route": "econ_finance_query",
                    "gold_evidence_ids": ["news:jjrb:v2"],
                    "should_answer": True,
                    "should_refuse": False,
                    "must_have_citations": True,
                    "case_type": "B_context_follow_up",
                    "notes": "",
                }
            ], limit=5, top_k=5, use_v2=True))
        finally:
            eval_context_rag._retrieve_once = original_retrieve_once

        self.assertEqual(calls[-1]["query"], "那它对制造业有什么影响？")
        self.assertIn("新质生产力", calls[-1]["vector_query"])
        self.assertIn("高质量发展", calls[-1]["vector_query"])
        self.assertIn("制造业", calls[-1]["vector_query"])
        self.assertTrue(calls[-1]["use_v2"])
        self.assertEqual(rows[0]["retrieval_query"], calls[-1]["vector_query"])

    def test_context_follow_carries_previous_evidence_ids_into_next_retrieval(self):
        calls = []
        original_retrieve_once = eval_context_rag._retrieve_once

        async def fake_retrieve_once(query, limit, top_k, **kwargs):
            calls.append({
                "query": query,
                "carryover_evidence_ids": kwargs.get("carryover_evidence_ids"),
            })
            refs = ["news:jjrb:af17afe835290422"] if len(calls) == 1 else ["news:jjrb:next"]
            return {
                "route": "econ_finance_query",
                "rag_route": None,
                "retrieved_evidence_ids": refs,
                "raw_evidence_ids": refs,
                "latency_ms": 1.0,
                "collection": "news_chunks_v2",
                "index_version": "v2_unified",
                "items_count": 1,
            }

        eval_context_rag._retrieve_once = fake_retrieve_once
        try:
            rows = asyncio.run(eval_context_rag.evaluate_retrieve_only([
                {
                    "id": "context_follow_anchor",
                    "turns": [
                        "科技保险为创新减震这篇报道讲了什么？",
                        "这个对科技企业风险保障有什么作用？",
                    ],
                    "expected_route": "econ_finance_query",
                    "gold_evidence_ids": ["news:jjrb:af17afe835290422"],
                    "should_answer": True,
                    "should_refuse": False,
                    "must_have_citations": True,
                    "case_type": "B_context_follow_up",
                    "notes": "",
                }
            ], limit=5, top_k=5, use_v2=True))
        finally:
            eval_context_rag._retrieve_once = original_retrieve_once

        self.assertEqual(calls[-1]["carryover_evidence_ids"], ["news:jjrb:af17afe835290422"])
        self.assertIn("科技保险为创新减震", rows[0]["retrieval_query"])


    def test_v2_api_rerank_uses_expanded_context_query(self):
        calls = []
        original_search = eval_context_rag.search_news_rag_v2
        original_api_rerank = eval_context_rag.api_rerank

        async def fake_search(query, **kwargs):
            return {
                "collection_route": "econ_finance_query",
                "rag_route": None,
                "evidence_ids": ["news:jjrb:af17afe835290422"],
                "collection_name": "news_chunks_v2",
                "index_version": "v2_unified",
                "items": [
                    {
                        "id": "jjrb:af17afe835290422",
                        "evidence_id": "news:jjrb:af17afe835290422",
                        "title": "科技保险为创新减震",
                        "summary": "科技企业风险保障",
                    }
                ],
            }

        async def fake_api_rerank(query, items, top_k, model=None):
            calls.append(query)
            return list(items), {"reranker_used": "fake_api"}

        eval_context_rag.search_news_rag_v2 = fake_search
        eval_context_rag.api_rerank = fake_api_rerank
        try:
            asyncio.run(eval_context_rag._retrieve_once(
                "对科技企业风险保障有什么作用？",
                limit=5,
                top_k=5,
                use_v2=True,
                vector_query="科技保险为创新减震 报道 对科技企业风险保障有什么作用？",
                intent_query="科技保险为创新减震 报道 对科技企业风险保障有什么作用？",
                use_api_rerank=True,
            ))
        finally:
            eval_context_rag.search_news_rag_v2 = original_search
            eval_context_rag.api_rerank = original_api_rerank

        self.assertEqual(calls, ["科技保险为创新减震 报道 对科技企业风险保障有什么作用？"])

    def test_v2_api_rerank_preserves_carryover_evidence_priority(self):
        original_search = eval_context_rag.search_news_rag_v2
        original_api_rerank = eval_context_rag.api_rerank

        async def fake_search(query, **kwargs):
            return {
                "collection_route": "econ_finance_query",
                "rag_route": None,
                "evidence_ids": ["news:jjrb:carry", "news:jjrb:other"],
                "collection_name": "news_chunks_v2",
                "index_version": "v2_unified",
                "items": [
                    {
                        "id": "jjrb:carry",
                        "evidence_id": "news:jjrb:carry",
                        "title": "Previous evidence",
                        "summary": "Previous evidence summary",
                        "_retrieval_channel": "carryover_evidence",
                        "score": 1.0,
                    },
                    {
                        "id": "jjrb:other",
                        "evidence_id": "news:jjrb:other",
                        "title": "Other evidence",
                        "summary": "Other evidence summary",
                        "score": 1.0,
                    },
                ],
            }

        async def fake_api_rerank(query, items, top_k, model=None):
            other = dict(items[1], rerank_score=0.86, api_rerank_score=0.86)
            carry = dict(items[0], rerank_score=0.82, api_rerank_score=0.82)
            return [other, carry], {"reranker_used": "fake_api"}

        eval_context_rag.search_news_rag_v2 = fake_search
        eval_context_rag.api_rerank = fake_api_rerank
        try:
            result = asyncio.run(eval_context_rag._retrieve_once(
                "它有什么作用？",
                limit=5,
                top_k=2,
                use_v2=True,
                vector_query="Previous evidence 它有什么作用？",
                intent_query="Previous evidence 它有什么作用？",
                carryover_evidence_ids=["news:jjrb:carry"],
                use_api_rerank=True,
            ))
        finally:
            eval_context_rag.search_news_rag_v2 = original_search
            eval_context_rag.api_rerank = original_api_rerank

        self.assertEqual(result["retrieved_evidence_ids"][0], "news:jjrb:carry")


if __name__ == "__main__":
    unittest.main()
