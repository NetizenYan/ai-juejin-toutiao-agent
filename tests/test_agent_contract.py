import asyncio
import unittest

from harness import agent
from harness.intent import build_fallback_tool_calls, detect_intent
from harness.tool_registry import ToolPolicyError, validate_tool_arguments


class AgentContractTests(unittest.TestCase):
    def test_detects_news_question_for_station_search(self):
        intent = detect_intent("最近有什么AI新闻可以看？")

        self.assertEqual(intent, "news_qa")

    def test_constraint_only_message_does_not_trigger_news_retrieval(self):
        intent = detect_intent("之后都简单点，不超过120字，并保留新闻证据引用。")

        self.assertEqual(intent, "general_chat")

    def test_economic_policy_terms_route_to_news_qa(self):
        self.assertEqual(detect_intent("新质生产力 高质量发展 制造业 那它对制造业有什么影响？"), "news_qa")
        self.assertEqual(detect_intent("那这个是不是一定利好半导体？"), "news_qa")
        self.assertEqual(detect_intent("人民日报是否确认量子白菜工程2028全面落地？"), "news_qa")
        self.assertEqual(detect_intent("那这和科技创新有什么关系？"), "news_qa")

    def test_investment_recommendation_boundary_is_not_article_recommendation(self):
        self.assertEqual(detect_intent("新质生产力 新能源 那它是不是可以推荐我买新能源股票？"), "news_qa")

    def test_fallback_routes_news_question_to_search_tool(self):
        calls = build_fallback_tool_calls("帮我找一下AI芯片相关资讯")

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "retrieve_news")
        self.assertEqual(calls[0]["arguments"]["query"], "帮我找一下AI芯片相关资讯")
        self.assertLessEqual(calls[0]["arguments"]["limit"], 50)

    def test_fallback_routes_recommendation_to_authenticated_history_tool(self):
        calls = build_fallback_tool_calls("给我推荐几篇文章", user_id=42)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "recommend_news")
        self.assertEqual(calls[0]["arguments"], {"limit": 5})

    def test_validates_tool_arguments_against_allowlist_and_schema(self):
        args = validate_tool_arguments("news_search", {"query": "AI", "limit": 3})

        self.assertEqual(args, {"query": "AI", "limit": 3})

    def test_injects_authenticated_user_id_for_history_tool(self):
        args = validate_tool_arguments("user_recent_history", {"limit": 3}, auth_user_id=42)

        self.assertEqual(args, {"user_id": 42, "limit": 3})

    def test_rejects_model_supplied_user_id_for_history_tool(self):
        with self.assertRaises(ToolPolicyError):
            validate_tool_arguments("user_recent_history", {"user_id": 99, "limit": 3}, auth_user_id=42)

    def test_rejects_unknown_tool_name(self):
        with self.assertRaises(ToolPolicyError):
            validate_tool_arguments("sql_query", {"sql": "select * from user"})

    def test_rejects_out_of_budget_tool_arguments(self):
        with self.assertRaises(ToolPolicyError):
            validate_tool_arguments("news_search", {"query": "AI", "limit": 100})

    def test_harness_executes_tools_through_mcp_client(self):
        async def fake_call_tool(session, name, arguments):
            self.assertEqual(session, "fake-mcp-session")
            self.assertEqual(name, "news_search")
            self.assertEqual(arguments, {"query": "AI", "limit": 3})
            return {"tool": name, "items": [], "evidence_ids": []}

        original = agent.call_tool
        agent.call_tool = fake_call_tool
        try:
            result = asyncio.run(
                agent._execute_calls(
                    "fake-mcp-session",
                    db=None,
                    calls=[{"name": "news_search", "arguments": {"query": "AI", "limit": 3}}],
                    audit_message_id=None,
                )
            )
        finally:
            agent.call_tool = original

        self.assertEqual(result, [{"tool": "news_search", "items": [], "evidence_ids": []}])

    def test_station_intent_uses_deterministic_tools_before_model_choice(self):
        calls = agent._deterministic_tool_calls("给我推荐几篇文章", user_id=42)

        self.assertEqual(calls, [{"name": "recommend_news", "arguments": {"limit": 5}}])

    def test_system_prompt_blocks_stock_prediction_and_advice(self):
        self.assertIn("不要预测个股涨跌", agent.DEFAULT_SYSTEM_PROMPT)
        self.assertIn("不要给买卖建议", agent.DEFAULT_SYSTEM_PROMPT)

    def test_answer_contract_prompt_blocks_stock_prediction_and_advice(self):
        contract_text = agent._contract_prompt(agent.AnswerContract())

        self.assertIn("不预测涨跌", contract_text)
        self.assertIn("不给买卖建议", contract_text)

    def test_unsupported_query_validation_forces_no_answer_even_in_shadow(self):
        validation = agent.AnswerValidationResult(
            passed=False,
            hallucination_risk="high",
            constraint_violations=["evidence_not_support_query"],
        )

        self.assertTrue(agent._should_force_no_answer(validation))

    def test_llm_timeout_uses_deterministic_evidence_fallback(self):
        class SlowClient:
            async def complete(self, _messages):
                await asyncio.sleep(0.05)
                return "late"

        answer = asyncio.run(
            agent._complete_with_fallback(
                SlowClient(),
                messages=[],
                tool_results=[{
                    "items": [{
                        "id": "jjrb:test",
                        "title": "新质生产力相关报道",
                        "summary": "summary",
                    }]
                }],
                contract=agent.AnswerContract(),
                timeout_seconds=0.001,
            )
        )

        self.assertIn("[news:jjrb:test]", answer)

    def test_model_visible_history_tool_schema_hides_user_id(self):
        tool_defs = [{
            "type": "function",
            "function": {
                "name": "user_recent_history",
                "description": "history",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "integer"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["user_id"],
                },
            },
        }]

        filtered = agent._filter_allowed_tool_defs(tool_defs)

        properties = filtered[0]["function"]["parameters"]["properties"]
        required = filtered[0]["function"]["parameters"].get("required", [])
        self.assertNotIn("user_id", properties)
        self.assertNotIn("user_id", required)

    def test_model_visible_retrieve_news_schema_hides_carryover_evidence_ids(self):
        tool_defs = [{
            "type": "function",
            "function": {
                "name": "retrieve_news",
                "description": "retrieve",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                        "carryover_evidence_ids": {"type": "array"},
                    },
                    "required": ["query"],
                },
            },
        }]

        filtered = agent._filter_allowed_tool_defs(tool_defs)

        properties = filtered[0]["function"]["parameters"]["properties"]
        self.assertNotIn("carryover_evidence_ids", properties)
        self.assertEqual(set(properties), {"query", "limit"})

    def test_carryover_evidence_is_boosted_before_parent_aggregation(self):
        ranked = [
            {
                "id": "jjrb:other",
                "evidence_id": "news:jjrb:other",
                "title": "Other evidence",
                "summary": "other",
                "rerank_score": 0.86,
            },
            {
                "id": "jjrb:carry",
                "evidence_id": "news:jjrb:carry",
                "title": "Carryover evidence",
                "summary": "carry",
                "rerank_score": 0.82,
                "_retrieval_channel": "carryover_evidence",
            },
        ]

        boosted = agent._boost_carryover_ranked_items(ranked, ["news:jjrb:carry"])
        parents = agent._aggregate_parents(boosted, 2)

        self.assertEqual(parents[0]["id"], "jjrb:carry")

    def test_parent_aggregation_preserves_anchor_resolution_metadata(self):
        parents = agent._aggregate_parents(
            [{
                "id": "jjrb:001",
                "evidence_id": "news:jjrb:001",
                "title": "因地制宜发展新质生产力",
                "summary": "经济日报报道新质生产力。",
                "source": "经济日报",
                "publish_time": "2024-05-12",
                "publish_ts": 1715472000,
                "rerank_score": 0.91,
            }],
            1,
        )

        self.assertEqual(parents[0]["evidence_id"], "news:jjrb:001")
        self.assertEqual(parents[0]["source"], "经济日报")
        self.assertEqual(parents[0]["publish_time"], "2024-05-12")

    def test_fuzzy_anchor_query_returns_confirmation_before_answering(self):
        resolution = agent.resolve_anchor_candidates(
            "我记得经济日报关于新质生产力的新闻",
            [{
                "id": "jjrb:001",
                "evidence_id": "news:jjrb:001",
                "title": "因地制宜发展新质生产力",
                "summary": "经济日报报道新质生产力。",
                "source": "经济日报",
                "publish_time": "2024-05-12",
            }],
        )

        text = agent.render_anchor_confirmation(resolution)

        self.assertIn("请确认", text)
        self.assertIn("news:jjrb:001", text)
        self.assertNotIn("结论是", text)

    def test_fuzzy_anchor_without_candidates_interrupts_for_external_research(self):
        resolution = agent.resolve_anchor_candidates("我记得Reuters关于新质生产力的新闻", [])

        self.assertTrue(agent._should_interrupt_for_anchor_resolution(resolution))
        text = agent.render_anchor_confirmation(resolution)
        self.assertIn("站内", text)
        self.assertIn("站外", text)
        self.assertIn("工具", text)

    def test_user_selection_confirms_prior_numbered_anchor(self):
        resolution = agent.resolve_anchor_candidates(
            "我记得经济日报关于新质生产力的新闻",
            [
                {
                    "id": "jjrb:first",
                    "evidence_id": "news:jjrb:first",
                    "title": "第一篇新质生产力报道",
                    "summary": "经济日报报道新质生产力。",
                    "source": "经济日报",
                    "publish_time": "2026-05-01",
                },
                {
                    "id": "jjrb:second",
                    "evidence_id": "news:jjrb:second",
                    "title": "第二篇新质生产力报道",
                    "summary": "经济日报报道新质生产力。",
                    "source": "经济日报",
                    "publish_time": "2026-05-02",
                },
            ],
        )
        history = [
            {"role": "user", "content": "我记得经济日报关于新质生产力的新闻"},
            {"role": "assistant", "content": agent.render_anchor_confirmation(resolution)},
            {"role": "user", "content": "就是第一篇，请按这篇解释"},
        ]

        confirmed = agent._confirmed_anchor_from_recent_confirmation(history)

        self.assertIsNotNone(confirmed)
        self.assertEqual(confirmed["anchor_id"], "news:jjrb:first")
        self.assertEqual(confirmed["match_confidence"], "confirmed")

    def test_web_search_items_feed_external_anchor_candidates(self):
        items = agent._external_anchor_items_from_tool_results([
            {
                "tool": "web_search",
                "items": [{
                    "title": "Reuters: China policy mentions new productive forces",
                    "url": "https://www.reuters.com/world/china/policy-new-productive-forces-2024-05-12/",
                    "summary": "Reuters reported a policy discussion about 新质生产力 in May 2024.",
                }],
                "evidence_ids": [
                    "web:https://www.reuters.com/world/china/policy-new-productive-forces-2024-05-12/"
                ],
            }
        ])

        resolution = agent.resolve_anchor_candidates(
            "我记得Reuters在2024年5月有一篇关于新质生产力政策表述的报道",
            items,
        )

        self.assertEqual(resolution.state, "WAITING_USER_CONFIRMATION")
        self.assertEqual(resolution.candidates[0].source_name, "Reuters")
        self.assertEqual(resolution.candidates[0].source_credibility, "medium")
        self.assertEqual(resolution.candidates[0].acquisition_method, "web_search")
        self.assertIn("reuters.com", resolution.candidates[0].source_url_or_evidence_id)

    def test_configured_review_safe_source_policy_keeps_low_external_item_as_lead(self):
        items = [{
            "id": "https://x.example/post/1",
            "source_url": "https://x.example/post/1",
            "url": "https://x.example/post/1",
            "title": "网传新质生产力相关消息",
            "summary": "社媒线索。",
            "source": "X",
            "source_credibility": "low",
            "verification_status": "unverified",
            "acquisition_method": "web_search",
        }]
        original_policy = getattr(agent.settings, "b_v3_source_policy", "local_test")
        object.__setattr__(agent.settings, "b_v3_source_policy", "review_safe")
        try:
            resolution = agent._resolve_anchor_candidates_for_current_policy(
                "我记得X上有一条关于新质生产力的新闻",
                items,
            )
        finally:
            object.__setattr__(agent.settings, "b_v3_source_policy", original_policy)

        self.assertEqual(resolution.candidates, [])
        self.assertEqual(len(resolution.leads), 1)
        self.assertEqual(resolution.state, "NEEDS_EXTERNAL_RESEARCH")

    def test_anchor_items_merge_internal_rag_and_external_web_search(self):
        items = agent._anchor_items_from_tool_results([
            {
                "tool": "retrieve_news",
                "items": [{
                    "id": "jjrb:1",
                    "evidence_id": "news:jjrb:1",
                    "title": "站内新质生产力报道",
                    "summary": "站内摘要",
                    "source": "经济日报",
                }],
            },
            {
                "tool": "web_search",
                "items": [{
                    "title": "Reuters report about 新质生产力",
                    "url": "https://www.reuters.com/world/china/new-productive-forces/",
                    "summary": "Reuters summary",
                }],
            },
        ])

        refs = {item.get("evidence_id") or item.get("source_url") for item in items}

        self.assertIn("news:jjrb:1", refs)
        self.assertIn("https://www.reuters.com/world/china/new-productive-forces/", refs)

    def test_anchor_items_include_web_capture_ocr_result(self):
        items = agent._anchor_items_from_tool_results([{
            "tool": "web_capture_ocr",
            "item": {
                "id": 7420,
                "evidence_id": "news:7420",
                "source_url": "https://x.example/post/1",
                "url": "https://x.example/post/1",
                "title": "外网页面截图 OCR 测试",
                "text": "新质生产力政策信号持续释放。",
                "source": "X",
                "source_credibility": "low",
                "verification_status": "unverified",
                "acquisition_method": "ocr_screenshot",
            },
        }])

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["evidence_id"], "news:7420")
        self.assertEqual(items[0]["acquisition_method"], "ocr_screenshot")
        self.assertEqual(items[0]["source_credibility"], "low")

    def test_anchor_resolution_metadata_preserves_external_verification(self):
        resolution = agent.resolve_anchor_candidates(
            "OCR X screenshot policy signal",
            [{
                "id": "ocr:x:001",
                "evidence_id": "https://x.example/post/1",
                "title": "External OCR policy signal",
                "summary": "Policy signal from an OCR screenshot.",
                "source": "X",
                "acquisition_method": "ocr_screenshot",
                "source_credibility": "low",
                "verification_status": "station_matched",
                "external_verification": {
                    "verification_status": "station_matched",
                    "matched_station_evidence_ids": ["news:station:1"],
                    "matched_station_titles": ["Station matched policy signal"],
                    "user_warning": "external OCR lead has station match but low source credibility",
                },
            }],
        )

        metadata = agent._anchor_resolution_metadata(resolution)

        external_verification = metadata["candidates"][0]["external_verification"]
        self.assertEqual(external_verification["verification_status"], "station_matched")
        self.assertEqual(external_verification["matched_station_evidence_ids"], ["news:station:1"])
        self.assertIn("low source credibility", external_verification["user_warning"])

    def test_confirmed_anchor_context_append_preserves_external_verification(self):
        context = agent.SessionContext(recent_messages=[], session_summary={})

        agent._append_confirmed_anchor_to_context(
            context,
            {
                "anchor_id": "https://x.example/post/1",
                "title": "External OCR policy signal",
                "source_name": "X",
                "source_url": "https://x.example/post/1",
                "source_credibility": "low",
                "verification_status": "station_matched",
                "acquisition_method": "ocr_screenshot",
                "external_verification": {
                    "verification_status": "station_matched",
                    "matched_station_evidence_ids": ["news:station:1"],
                },
            },
        )

        self.assertEqual(
            context.anchor_ledger[0]["external_verification"]["matched_station_evidence_ids"],
            ["news:station:1"],
        )

    def test_agent_orchestration_metadata_splits_anchor_workflow_roles(self):
        resolution = agent.resolve_anchor_candidates(
            "OCR X screenshot policy signal",
            [{
                "id": "ocr:x:001",
                "evidence_id": "https://x.example/post/1",
                "title": "External OCR policy signal",
                "summary": "Policy signal from an OCR screenshot.",
                "source": "X",
                "acquisition_method": "ocr_screenshot",
                "source_credibility": "low",
                "verification_status": "station_matched",
                "external_verification": {
                    "verification_status": "station_matched",
                    "matched_station_evidence_ids": ["news:station:1"],
                    "matched_station_titles": ["Station matched policy signal"],
                },
            }],
        )
        context = agent.SessionContext(
            recent_messages=[],
            session_summary={},
            anchor_ledger=[{
                "anchor_id": "news:prior",
                "title": "Prior confirmed anchor",
                "match_confidence": "confirmed",
                "source_credibility": "high",
            }],
            topic_ledger=[{"topic_id": "topic:1", "topic": "policy signal"}],
        )

        metadata = agent._build_agent_orchestration_metadata(
            latest_user="OCR X screenshot policy signal",
            retrieval_user="External OCR policy signal OCR X screenshot policy signal",
            intent="web_research",
            allowed_tools={"web_capture_ocr", "web_search"},
            tool_results=[{
                "tool": "web_capture_ocr",
                "item": {
                    "source": "X",
                    "external_verification": {
                        "verification_status": "station_matched",
                        "matched_station_evidence_ids": ["news:station:1"],
                    },
                },
            }],
            anchor_resolution=resolution,
            confirmed_anchor=None,
            session_context=context,
            carryover_evidence_ids=["news:prior"],
        )

        roles = {role["role"]: role for role in metadata["roles"]}
        self.assertEqual(
            list(roles),
            ["QueryUnderstanding", "MemoryLedger", "AnchorResolver", "EvidenceVerifier", "AnswerPlanner"],
        )
        self.assertTrue(roles["QueryUnderstanding"]["details"]["anchor_query"])
        self.assertEqual(roles["MemoryLedger"]["details"]["carryover_evidence_ids"], ["news:prior"])
        self.assertEqual(roles["AnchorResolver"]["details"]["state"], "WAITING_USER_CONFIRMATION")
        self.assertEqual(roles["EvidenceVerifier"]["details"]["station_matched_count"], 1)
        self.assertEqual(metadata["next_action"], "ask_user_to_confirm_anchor")
        self.assertTrue(metadata["interrupt_user"])

    def test_record_validation_preserves_agent_orchestration_metadata(self):
        sink = {
            "agent_orchestration": {
                "next_action": "ask_user_to_confirm_anchor",
                "roles": [{"role": "AnswerPlanner", "action": "ask_user_to_confirm_anchor"}],
            }
        }

        agent._record_validation(
            sink,
            agent.AnswerValidationResult(passed=True, hallucination_risk="low"),
            mode="shadow",
            rewrite_count=0,
            route="econ_finance_query",
        )

        self.assertIn("agent_orchestration", sink)
        self.assertEqual(sink["agent_orchestration"]["next_action"], "ask_user_to_confirm_anchor")

    def test_memory_recall_fast_path_skips_tools_and_llm(self):
        class ExplodingClient:
            async def complete(self, _messages):
                raise AssertionError("memory recall fast path should not call LLM complete")

            async def complete_message(self, *_args, **_kwargs):
                raise AssertionError("memory recall fast path should not call LLM tool planning")

            async def stream_content(self, _messages):
                raise AssertionError("memory recall fast path should not stream from LLM")
                yield ""

        async def exploding_list_tool_defs(_session):
            raise AssertionError("memory recall fast path should not list tools")

        async def collect_answer(history, sink):
            parts = []
            async for token in agent.run_chat(history, validation_sink=sink):
                parts.append(token)
            return "".join(parts)

        history = [
            {
                "role": "assistant",
                "content": "上一轮摘要",
                "evidence": {
                    "context": {
                        "topic_ledger": [{
                            "topic_id": "topic:1",
                            "first_turn_index": 1,
                            "last_mentioned_turn_index": 1,
                            "topic_terms": ["新质生产力"],
                            "source_terms": ["经济日报"],
                            "time_terms": ["2026-05"],
                            "related_anchor_ids": ["news:jjrb:2f10cd7d951a34dc"],
                        }],
                        "anchor_ledger": [{
                            "anchor_id": "news:jjrb:2f10cd7d951a34dc",
                            "title": "在发展新质生产力上走在前列",
                            "source_name": "jjrb",
                            "evidence_id_or_url": "news:jjrb:2f10cd7d951a34dc",
                            "match_confidence": "confirmed",
                            "source_credibility": "high",
                            "verification_status": "station_internal",
                            "acquisition_method": "rag",
                            "user_confirmed": True,
                            "confirmed_turn_index": 2,
                        }],
                        "last_evidence_ids": ["news:jjrb:2f10cd7d951a34dc"],
                    }
                },
            },
            {"role": "user", "content": "第100轮：我们最开始聊的主题和确认过的新闻锚点是什么？"},
        ]

        original_client = agent.LLMClient
        original_list_tool_defs = agent.list_tool_defs
        agent.LLMClient = ExplodingClient
        agent.list_tool_defs = exploding_list_tool_defs
        try:
            sink = {}
            answer = asyncio.run(collect_answer(history, sink))
        finally:
            agent.LLMClient = original_client
            agent.list_tool_defs = original_list_tool_defs

        self.assertIn("最初主题", answer)
        self.assertIn("经济日报", answer)
        self.assertIn("新质生产力", answer)
        self.assertIn("确认过的新闻锚点", answer)
        self.assertIn("news:jjrb:2f10cd7d951a34dc", answer)
        self.assertIn("不作为新闻事实证据", answer)
        self.assertEqual(sink["agent_orchestration"]["next_action"], "answer_from_memory_ledger")

    def test_format_confirmation_fast_path_skips_tools_and_llm(self):
        class ExplodingClient:
            async def complete(self, _messages):
                raise AssertionError("format confirmation fast path should not call LLM complete")

            async def complete_message(self, *_args, **_kwargs):
                raise AssertionError("format confirmation fast path should not call LLM tool planning")

            async def stream_content(self, _messages):
                raise AssertionError("format confirmation fast path should not stream from LLM")
                yield ""

        async def exploding_list_tool_defs(_session):
            raise AssertionError("format confirmation fast path should not list tools")

        async def collect_answer(history, sink):
            parts = []
            async for token in agent.run_chat(history, validation_sink=sink):
                parts.append(token)
            return "".join(parts)

        original_client = agent.LLMClient
        original_list_tool_defs = agent.list_tool_defs
        agent.LLMClient = ExplodingClient
        agent.list_tool_defs = exploding_list_tool_defs
        try:
            sink = {}
            answer = asyncio.run(
                collect_answer(
                    [{"role": "user", "content": "第50轮只是格式确认。"}],
                    sink,
                )
            )
        finally:
            agent.LLMClient = original_client
            agent.list_tool_defs = original_list_tool_defs

        self.assertIn("收到", answer)
        self.assertIn("格式", answer)
        self.assertEqual(sink["agent_orchestration"]["next_action"], "acknowledge_format_only_turn")

    def test_ocr_comparison_attaches_simple_station_match_when_internal_item_exists(self):
        results = [
            {
                "tool": "retrieve_news",
                "items": [{
                    "id": 1,
                    "evidence_id": "news:1",
                    "title": "新质生产力政策信号",
                    "summary": "高质量发展、科技创新和产业升级成为关键词。",
                    "source": "经济日报",
                }],
            },
            {
                "tool": "web_capture_ocr",
                "item": {
                    "id": 7420,
                    "evidence_id": "news:7420",
                    "title": "外网页面截图 OCR 测试",
                    "text": "新质生产力政策信号持续释放，高质量发展和科技创新成为关键词。",
                    "source": "X",
                    "source_credibility": "low",
                    "verification_status": "unverified",
                    "acquisition_method": "ocr_screenshot",
                },
            },
        ]

        agent._attach_ocr_comparisons(results)

        comparison = results[1]["ocr_comparison"]
        self.assertTrue(comparison["matched"])
        self.assertEqual(comparison["station_evidence_id"], "news:1")
        self.assertIn("新质生产力", comparison["overlap_terms"])
        self.assertEqual(results[1]["item"]["ocr_comparison"], comparison)
        self.assertEqual(results[1]["item"]["verification_status"], "station_matched")
        self.assertEqual(results[1]["item"]["external_verification"]["verification_status"], "station_matched")
        self.assertIn("user_warning", results[1]["item"]["external_verification"])

    def test_ocr_comparison_skips_when_station_has_no_candidate(self):
        results = [{
            "tool": "web_capture_ocr",
            "item": {
                "title": "外网页面截图 OCR 测试",
                "text": "新质生产力政策信号持续释放。",
                "source": "X",
            },
        }]

        agent._attach_ocr_comparisons(results)

        self.assertNotIn("ocr_comparison", results[0])

    def test_station_compare_query_for_web_ocr_uses_user_text_and_ocr_excerpt(self):
        query = agent._station_compare_query_for_web_ocr(
            "帮我看一下 https://x.example/post/1 这篇关于政策信号的新闻",
            [{
                "tool": "web_capture_ocr",
                "item": {
                    "title": "外网页面截图 OCR 测试",
                    "text": "新质生产力政策信号持续释放，高质量发展成为关键词。",
                },
            }],
        )

        self.assertIn("政策信号", query)
        self.assertIn("新质生产力", query)
        self.assertNotIn("https://x.example/post/1", query)

    def test_station_compare_query_is_empty_without_ocr_capture_result(self):
        query = agent._station_compare_query_for_web_ocr(
            "帮我看一下 https://x.example/post/1",
            [{"tool": "web_fetch", "text": "plain text"}],
        )

        self.assertEqual(query, "")

    def test_anchor_resolution_metadata_carries_source_labels_without_bulk_text(self):
        resolution = agent.resolve_anchor_candidates(
            "Reuters: China policy mentions new productive forces",
            [{
                "id": "https://www.reuters.com/world/china/policy-new-productive-forces-2024-05-12/",
                "source_url": "https://www.reuters.com/world/china/policy-new-productive-forces-2024-05-12/",
                "url": "https://www.reuters.com/world/china/policy-new-productive-forces-2024-05-12/",
                "title": "Reuters: China policy mentions new productive forces",
                "summary": "x" * 5000,
                "source": "Reuters",
                "source_credibility": "medium",
                "verification_status": "unverified",
                "acquisition_method": "web_search",
                "publish_time": "2024-05-12",
            }],
        )

        metadata = agent._anchor_resolution_metadata(resolution)

        self.assertEqual(metadata["state"], "WAITING_USER_CONFIRMATION")
        self.assertEqual(metadata["candidate_count"], 1)
        self.assertEqual(metadata["candidates"][0]["source_credibility"], "medium")
        self.assertEqual(metadata["candidates"][0]["acquisition_method"], "web_search")
        self.assertEqual(metadata["candidates"][0]["source_url"], "https://www.reuters.com/world/china/policy-new-productive-forces-2024-05-12/")
        self.assertNotIn("summary", metadata["candidates"][0])
        self.assertNotIn("snippet", metadata["candidates"][0])
        self.assertNotIn("text", metadata["candidates"][0])

    def test_low_credibility_warning_names_source_and_limits_fact_claim(self):
        warning = agent._source_credibility_warning({
            "source_name": "X",
            "source_credibility": "low",
            "verification_status": "unverified",
        })

        self.assertIn("X", warning)
        self.assertIn("可信度较低", warning)
        self.assertIn("不作为确定事实", warning)

    def test_low_credibility_confirmed_anchor_warning_enters_generation_prompt(self):
        context = agent.SessionContext(
            recent_messages=[],
            session_summary={},
            anchor_ledger=[{
                "anchor_id": "https://x.example/post/1",
                "title": "X 上的新质生产力线索",
                "source_name": "X",
                "source_credibility": "low",
                "verification_status": "unverified",
                "acquisition_method": "web_search",
                "match_confidence": "confirmed",
                "user_confirmed": True,
            }],
        )

        messages = agent._build_final_messages([], [], session_context=context)
        prompt = "\n".join(message["content"] for message in messages)

        self.assertIn("X", prompt)
        self.assertIn("可信度较低", prompt)
        self.assertIn("不作为确定事实", prompt)

    def test_medium_external_confirmed_anchor_warning_enters_generation_prompt(self):
        context = agent.SessionContext(
            recent_messages=[],
            session_summary={},
            anchor_ledger=[{
                "anchor_id": "https://www.reuters.com/world/china/policy/",
                "title": "Reuters policy report",
                "source_name": "Reuters",
                "source_credibility": "medium",
                "verification_status": "unverified",
                "acquisition_method": "web_search",
                "match_confidence": "confirmed",
                "user_confirmed": True,
            }],
        )

        messages = agent._build_final_messages([], [], session_context=context)
        prompt = "\n".join(message["content"] for message in messages)

        self.assertIn("Reuters", prompt)
        self.assertIn("可信度中等", prompt)
        self.assertIn("不是站内已确认事实", prompt)

    def test_low_credibility_warning_is_prefixed_when_answer_omits_it(self):
        context = agent.SessionContext(
            recent_messages=[],
            session_summary={},
            anchor_ledger=[{
                "anchor_id": "https://x.example/post/1",
                "title": "X 上的新质生产力线索",
                "source_name": "X",
                "source_credibility": "low",
                "verification_status": "unverified",
                "acquisition_method": "web_search",
                "match_confidence": "confirmed",
                "user_confirmed": True,
            }],
        )

        answer = agent._ensure_confirmed_anchor_warning("这是基于线索的分析。", context)

        self.assertTrue(answer.startswith("注意：这条信息来自 X"))
        self.assertIn("可信度较低", answer)
        self.assertIn("不作为确定事实", answer)
        self.assertIn("这是基于线索的分析。", answer)

    def test_existing_low_credibility_warning_is_not_duplicated(self):
        context = agent.SessionContext(
            recent_messages=[],
            session_summary={},
            anchor_ledger=[{
                "anchor_id": "https://x.example/post/1",
                "source_name": "X",
                "source_credibility": "low",
                "verification_status": "unverified",
                "match_confidence": "confirmed",
                "user_confirmed": True,
            }],
        )
        original = "注意：这条信息来自 X，可信度较低；以下只能作为线索分析，不作为确定事实。正文。"

        answer = agent._ensure_confirmed_anchor_warning(original, context)

        self.assertEqual(answer, original)

    def test_record_validation_preserves_b_v3_anchor_metadata(self):
        sink = {
            "anchor_resolution": {
                "state": "WAITING_USER_CONFIRMATION",
                "requires_user_confirmation": True,
            },
            "confirmed_anchor": {
                "anchor_id": "news:jjrb:anchor",
                "source_credibility": "high",
            },
        }

        agent._record_validation(
            sink,
            agent.AnswerValidationResult(passed=True, hallucination_risk="low"),
            mode="shadow",
            rewrite_count=0,
            route="econ_finance_query",
        )

        self.assertEqual(sink["anchor_resolution"]["state"], "WAITING_USER_CONFIRMATION")
        self.assertEqual(sink["confirmed_anchor"]["anchor_id"], "news:jjrb:anchor")
        self.assertIn("metadata", sink)
        self.assertIn("summary", sink)


if __name__ == "__main__":
    unittest.main()
