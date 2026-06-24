import unittest

from harness import context_manager as cm
from harness.answer_contract import build_answer_contract
from harness.context_manager import (
    build_contextual_retrieval_query,
    build_session_context,
    render_session_context_section,
)
from harness.query_understanding import understand_user_query


def _msg(role: str, content: str, evidence=None):
    message = {"role": role, "content": content}
    if evidence is not None:
        message["evidence"] = evidence
    return message


class ContextManagerTests(unittest.TestCase):
    def test_keeps_recent_six_turns_as_original_messages(self):
        history = []
        for index in range(8):
            history.append(_msg("user", f"用户问题 {index}"))
            history.append(_msg("assistant", f"助手回答 {index}"))

        context = build_session_context(history, recent_turns=6)

        self.assertEqual(len(context.recent_messages), 12)
        self.assertEqual(context.recent_messages[0]["content"], "用户问题 2")
        self.assertEqual(context.recent_messages[-1]["content"], "助手回答 7")

    def test_message_count_over_twelve_triggers_structured_summary(self):
        history = [_msg("user" if index % 2 == 0 else "assistant", f"消息 {index}") for index in range(13)]

        context = build_session_context(history, message_threshold=12)

        self.assertTrue(context.compression_triggered)
        self.assertIsInstance(context.session_summary, dict)
        self.assertEqual(
            set(context.session_summary.keys()),
            {
                "user_goal",
                "confirmed_topics",
                "active_constraints",
                "open_questions",
                "last_valid_state",
                "last_route",
                "last_evidence_ids",
                "relevant_preferences",
            },
        )

    def test_total_chars_over_threshold_triggers_summary(self):
        history = [_msg("user", "最近财政政策有什么新闻？" + "很长" * 3100)]

        context = build_session_context(history, char_threshold=6000)

        self.assertTrue(context.compression_triggered)
        self.assertIsNotNone(context.session_summary)

    def test_compression_builds_bounded_long_context_memory_from_older_messages(self):
        history = []
        for index in range(8):
            history.append(_msg("user", f"早期讨论 {index}: {cm._TOPIC_KEYWORDS[0]} {cm._TOPIC_KEYWORDS[5]} " + "很长" * 80))
            history.append(_msg("assistant", f"早期回答 {index}: [news:jjrb:old{index}] " + "很长" * 80))
        history.extend([
            _msg("user", "最近一轮只是格式要求"),
            _msg("assistant", "好的。"),
        ])

        context = build_session_context(
            history,
            recent_turns=1,
            message_threshold=4,
            long_context_max_chars=520,
            long_context_message_char_limit=80,
        )

        self.assertTrue(context.compression_triggered)
        self.assertIsNotNone(context.long_context_memory)
        self.assertFalse(context.long_context_memory["use_as_evidence"])
        self.assertLessEqual(context.long_context_memory["estimated_chars"], 520)
        self.assertGreater(
            context.long_context_memory["source_message_count"],
            context.long_context_memory["compressed_message_count"],
        )
        self.assertEqual(len(context.recent_messages), 2)
        self.assertIn("compressed_messages", context.long_context_memory)

    def test_long_context_memory_is_rendered_as_non_evidence(self):
        history = []
        for index in range(7):
            history.append(_msg("user", f"早期讨论 {index}: {cm._TOPIC_KEYWORDS[0]}"))
            history.append(_msg("assistant", f"早期回答 {index}: [news:jjrb:old{index}]"))

        context = build_session_context(history, recent_turns=1, message_threshold=4)
        metadata = context.to_metadata()
        rendered = render_session_context_section(context)

        self.assertIn("long_context_memory", metadata)
        self.assertFalse(metadata["long_context_memory"]["use_as_evidence"])
        self.assertIn('<long_context_memory use_as_evidence="false">', rendered)
        self.assertIn("not factual evidence", rendered)

    def test_follow_up_can_use_long_context_memory_when_summary_is_disabled(self):
        history = [
            _msg("user", f"最开始我们讨论{cm._TOPIC_KEYWORDS[0]}和{cm._TOPIC_KEYWORDS[5]}的报道。"),
            _msg("assistant", "有相关报道。[news:jjrb:oldtopic]"),
            _msg("user", "中间只是格式要求。"),
            _msg("assistant", "好的。"),
            _msg("user", "那它有什么影响？"),
        ]

        context = build_session_context(
            history,
            recent_turns=1,
            message_threshold=2,
            session_summary_enabled=False,
        )
        expanded = build_contextual_retrieval_query("那它有什么影响？", context)

        self.assertIn(cm._TOPIC_KEYWORDS[0], expanded)
        self.assertIn(cm._TOPIC_KEYWORDS[5], expanded)
        self.assertFalse(context.memory_is_evidence)

    def test_topic_ledger_recalls_first_turn_at_round_100(self):
        history = [
            _msg("user", "第一轮我想找经济日报关于新质生产力的报道。"),
            _msg("assistant", "我会先找候选。[news:jjrb:first-anchor]"),
        ]
        for index in range(2, 101):
            history.append(_msg("user", f"第{index}轮只是格式确认。"))
            history.append(_msg("assistant", "好的。"))

        context = build_session_context(
            history,
            recent_turns=3,
            message_threshold=12,
            long_context_max_chars=1800,
            long_context_message_char_limit=120,
        )

        topic_terms = {
            term
            for entry in context.topic_ledger
            for term in entry.get("topic_terms", [])
        }
        source_terms = {
            term
            for entry in context.topic_ledger
            for term in entry.get("source_terms", [])
        }

        self.assertIn("新质生产力", topic_terms)
        self.assertIn("经济日报", source_terms)
        self.assertLessEqual(context.topic_ledger[0]["first_turn_index"], 1)
        self.assertFalse(context.memory_is_evidence)

    def test_incremental_ledgers_merge_previous_context_when_recent_history_is_truncated(self):
        previous = {
            "type": "session_summary",
            "use_as_evidence": False,
            "summary": {
                "user_goal": "first turn anchor lookup",
                "confirmed_topics": [cm._TOPIC_KEYWORDS[0]],
                "active_constraints": [],
                "open_questions": [],
                "last_valid_state": {},
                "last_route": "news_qa",
                "last_evidence_ids": ["news:jjrb:first-anchor"],
                "relevant_preferences": [],
            },
            "last_evidence_ids": ["news:jjrb:first-anchor"],
            "topic_ledger": [{
                "topic_id": "topic:first",
                "first_turn_index": 1,
                "last_mentioned_turn_index": 1,
                "topic_terms": [cm._TOPIC_KEYWORDS[0]],
                "source_terms": [cm._SOURCE_KEYWORDS[0]],
                "time_terms": ["2024-05"],
                "related_anchor_ids": ["news:jjrb:first-anchor"],
            }],
            "anchor_ledger": [{
                "anchor_id": "news:jjrb:first-anchor",
                "title": "First confirmed policy anchor",
                "source_name": cm._SOURCE_KEYWORDS[0],
                "evidence_id_or_url": "news:jjrb:first-anchor",
                "match_confidence": "confirmed",
                "source_credibility": "high",
                "verification_status": "station_internal",
                "acquisition_method": "rag",
                "user_confirmed": True,
                "confirmed_turn_index": 1,
            }],
            "evidence_ledger": [{
                "evidence_ref": "news:jjrb:first-anchor",
                "anchor_id": "news:jjrb:first-anchor",
                "source_type": "station_internal",
                "retrieval_turn_index": 1,
                "credibility_label": "high",
                "validation_notes": "",
            }],
        }
        follow_up = f"{cm._FOLLOW_UP_MARKERS[0]} manufacturing impact"
        history = [
            _msg("user", follow_up),
        ]

        context = build_session_context(history, previous_summary=previous, recent_turns=1)
        expanded = build_contextual_retrieval_query(follow_up, context)

        self.assertIn("news:jjrb:first-anchor", context.last_evidence_ids)
        self.assertIn(cm._TOPIC_KEYWORDS[0], {term for entry in context.topic_ledger for term in entry.get("topic_terms", [])})
        self.assertEqual(context.anchor_ledger[0]["anchor_id"], "news:jjrb:first-anchor")
        self.assertEqual(context.evidence_ledger[0]["evidence_ref"], "news:jjrb:first-anchor")
        self.assertIn(cm._TOPIC_KEYWORDS[0], expanded)
        self.assertIn("First confirmed policy anchor", expanded)
        self.assertEqual(context.ledger_state["merge_strategy"], "previous_context_incremental")
        self.assertFalse(context.memory_is_evidence)

    def test_incremental_anchor_merge_preserves_external_verification_on_duplicate_anchor(self):
        previous = {
            "summary": {
                "user_goal": "",
                "confirmed_topics": [],
                "active_constraints": [],
                "open_questions": [],
                "last_valid_state": {},
                "last_route": "",
                "last_evidence_ids": ["https://x.example/post/1"],
                "relevant_preferences": [],
            },
            "anchor_ledger": [{
                "anchor_id": "https://x.example/post/1",
                "title": "External OCR policy signal",
                "source_name": "X",
                "evidence_id_or_url": "https://x.example/post/1",
                "match_confidence": "confirmed",
                "source_credibility": "low",
                "verification_status": "station_matched",
                "acquisition_method": "ocr_screenshot",
                "user_confirmed": True,
                "confirmed_turn_index": 1,
                "external_verification": {
                    "verification_status": "station_matched",
                    "matched_station_evidence_ids": ["news:station:1"],
                },
            }],
        }
        history = [
            _msg(
                "assistant",
                "confirmed again",
                evidence={
                    "confirmed_anchor": {
                        "anchor_id": "https://x.example/post/1",
                        "title": "External OCR policy signal",
                        "source_name": "X",
                        "source_credibility": "low",
                        "verification_status": "station_matched",
                        "acquisition_method": "ocr_screenshot",
                    },
                },
            ),
        ]

        context = build_session_context(history, previous_summary=previous)

        self.assertEqual(len(context.anchor_ledger), 1)
        self.assertEqual(
            context.anchor_ledger[0]["external_verification"]["matched_station_evidence_ids"],
            ["news:station:1"],
        )

    def test_incremental_summary_keeps_previous_confirmed_topics_when_current_window_has_none(self):
        previous = {
            "summary": {
                "user_goal": "first turn anchor lookup",
                "confirmed_topics": [cm._TOPIC_KEYWORDS[0]],
                "active_constraints": [],
                "open_questions": [],
                "last_valid_state": {},
                "last_route": "news_qa",
                "last_evidence_ids": ["news:jjrb:first-anchor"],
                "relevant_preferences": [],
            },
        }
        history = [
            _msg("user", "format only"),
            _msg("assistant", "ok"),
        ]

        context = build_session_context(history, previous_summary=previous)

        self.assertIn(cm._TOPIC_KEYWORDS[0], context.session_summary["confirmed_topics"])
        self.assertIn("news:jjrb:first-anchor", context.session_summary["last_evidence_ids"])

    def test_anchor_ledger_keeps_confirmed_anchor_and_credibility_separate(self):
        history = [
            _msg("user", "我说的是第一篇，请按这篇继续。"),
            _msg(
                "assistant",
                "已确认候选：经济日报《因地制宜发展新质生产力》。[news:jjrb:anchor001]",
                evidence={
                    "confirmed_anchor": {
                        "anchor_id": "news:jjrb:anchor001",
                        "title": "因地制宜发展新质生产力",
                        "source_name": "经济日报",
                        "source_credibility": "high",
                        "verification_status": "station_internal",
                        "acquisition_method": "rag",
                    }
                },
            ),
        ]

        context = build_session_context(history)

        self.assertEqual(context.anchor_ledger[0]["anchor_id"], "news:jjrb:anchor001")
        self.assertEqual(context.anchor_ledger[0]["match_confidence"], "confirmed")
        self.assertEqual(context.anchor_ledger[0]["source_credibility"], "high")
        self.assertEqual(context.anchor_ledger[0]["verification_status"], "station_internal")

    def test_summary_is_marked_as_non_evidence(self):
        history = [
            _msg("user", "最近新质生产力有什么新闻？"),
            _msg("assistant", "有相关报道。[news:jjrb:8dcc9e6349959132]"),
        ]

        context = build_session_context(history)
        metadata = context.to_metadata()
        rendered = render_session_context_section(context)

        self.assertFalse(context.memory_is_evidence)
        self.assertFalse(metadata["use_as_evidence"])
        self.assertEqual(metadata["type"], "session_summary")
        self.assertIn('<session_context use_as_evidence="false">', rendered)
        self.assertIn("不可作为新闻事实来源", rendered)

    def test_active_constraints_continue_across_turns(self):
        history = [
            _msg("user", "之后都简单点，并保留引用。"),
            _msg("assistant", "好的。"),
            _msg("user", "最近财政政策有什么新闻？"),
        ]

        context = build_session_context(history)

        self.assertEqual(context.active_constraints["style"], "plain_language")
        self.assertEqual(context.active_constraints["detail_level"], "brief")
        self.assertTrue(context.active_constraints["must_include_citations"])

    def test_current_explicit_constraint_overrides_history_preference(self):
        history = [
            _msg("user", "之后都简单点。"),
            _msg("assistant", "好的。"),
            _msg("user", "这次请详细分析最近财政政策有什么变化。"),
        ]

        context = build_session_context(history)

        self.assertEqual(context.active_constraints["detail_level"], "detail")

    def test_last_evidence_ids_are_recorded_but_not_fact_evidence(self):
        history = [
            _msg("user", "最近高质量发展有什么新闻？"),
            _msg("assistant", "有相关报道。[news:jjrb:abc123]"),
            _msg("user", "那它对制造业有什么影响？"),
        ]

        context = build_session_context(history)
        rendered = render_session_context_section(context)

        self.assertIn("news:jjrb:abc123", context.last_evidence_ids)
        self.assertFalse(context.memory_is_evidence)
        self.assertIn("最近 evidence id 仅用于理解指代", rendered)

    def test_summary_refreshes_topics_when_previous_summary_exists(self):
        previous = {
            "type": "session_summary",
            "summary": {
                "user_goal": "之后都简单点",
                "confirmed_topics": [],
                "active_constraints": ["detail_level=brief"],
                "open_questions": [],
                "last_valid_state": {},
                "last_route": "",
                "last_evidence_ids": [],
                "relevant_preferences": [],
            },
        }
        history = [
            _msg("user", "之后都简单点。"),
            _msg("assistant", "好的。"),
            _msg("user", "最近高质量发展和新质生产力有什么新闻？"),
        ]

        context = build_session_context(history, previous_summary=previous)

        self.assertIn("高质量发展", context.session_summary["confirmed_topics"])
        self.assertIn("新质生产力", context.session_summary["confirmed_topics"])

    def test_contextual_follow_up_expands_retrieval_query_without_using_memory_as_evidence(self):
        history = [
            _msg("user", "最近高质量发展和新质生产力有什么新闻？"),
            _msg("assistant", "有相关报道。[news:jjrb:abc123]"),
            _msg("user", "那它对制造业有什么影响？"),
        ]
        context = build_session_context(history)

        expanded = build_contextual_retrieval_query("那它对制造业有什么影响？", context)

        self.assertIn("高质量发展", expanded)
        self.assertIn("新质生产力", expanded)
        self.assertIn("制造业", expanded)
        self.assertFalse(context.memory_is_evidence)

    def test_retrieval_query_removes_generation_instructions_but_keeps_source_time_and_topic(self):
        context = build_session_context([])

        cleaned = build_contextual_retrieval_query(
            "请只看经济日报，2026年5月新质生产力有什么报道？简单说，带引用，回答一下。",
            context,
        )

        self.assertIn("经济日报", cleaned)
        self.assertIn("2026年5月", cleaned)
        self.assertIn("新质生产力", cleaned)
        self.assertNotIn("简单说", cleaned)
        self.assertNotIn("带引用", cleaned)
        self.assertNotIn("回答一下", cleaned)

    def test_contextual_follow_up_restores_prior_source_and_topic(self):
        history = [
            _msg("user", "经济日报关于新质生产力有什么报道？"),
            _msg("assistant", "有相关报道。[news:jjrb:abc123]"),
            _msg("user", "那这和科技创新有什么关系？"),
        ]
        context = build_session_context(history)

        expanded = build_contextual_retrieval_query("那这和科技创新有什么关系？", context)

        self.assertIn("经济日报", expanded)
        self.assertIn("新质生产力", expanded)
        self.assertIn("科技创新", expanded)

    def test_follow_up_strips_pronoun_na_ta_for_cleaner_embedding(self):
        history = [
            _msg("user", "最近高质量发展和新质生产力有什么新闻？"),
            _msg("assistant", "有相关报道。[news:jjrb:abc123]"),
            _msg("user", "那它对制造业有什么影响？简单说，带引用。"),
        ]
        context = build_session_context(history)

        expanded = build_contextual_retrieval_query("那它对制造业有什么影响？简单说，带引用。", context)

        self.assertIn("高质量发展", expanded)
        self.assertIn("新质生产力", expanded)
        self.assertIn("制造业", expanded)
        self.assertNotIn("那它", expanded)

    def test_follow_up_strips_pronoun_na_zhe_ge_for_cleaner_embedding(self):
        history = [
            _msg("user", "最近新质生产力有什么新闻？"),
            _msg("assistant", "有相关报道。[news:jjrb:abc123]"),
            _msg("user", "那这个对产业升级有什么启发？"),
        ]
        context = build_session_context(history)

        expanded = build_contextual_retrieval_query("那这个对产业升级有什么启发？", context)

        self.assertIn("新质生产力", expanded)
        self.assertIn("产业升级", expanded)
        self.assertNotIn("那这个", expanded)
        self.assertNotIn("个对", expanded)

    def test_follow_up_strips_pronoun_zhe_ge_for_cleaner_embedding(self):
        history = [
            _msg("user", "最近高质量发展有什么新闻？"),
            _msg("assistant", "有相关报道。[news:jjrb:abc123]"),
            _msg("user", "这个和新质生产力有关吗？带引用。"),
        ]
        context = build_session_context(history)

        expanded = build_contextual_retrieval_query("这个和新质生产力有关吗？带引用。", context)

        self.assertIn("高质量发展", expanded)
        self.assertIn("新质生产力", expanded)
        self.assertNotIn("这个", expanded)

    def test_follow_up_strips_pronoun_gang_cai_na_ge_for_cleaner_embedding(self):
        history = [
            _msg("user", "高质量发展和新质生产力有什么报道？"),
            _msg("assistant", "有相关报道。[news:jjrb:abc123]"),
            _msg("user", "刚才那个对先进制造有什么影响？"),
        ]
        context = build_session_context(history)

        expanded = build_contextual_retrieval_query("刚才那个对先进制造有什么影响？", context)

        self.assertIn("新质生产力", expanded)
        self.assertIn("高质量发展", expanded)
        self.assertIn("先进制造", expanded)
        self.assertNotIn("刚才那个", expanded)

    def test_follow_up_keeps_pronoun_when_stripping_leaves_too_little_signal(self):
        history = [
            _msg("user", "最近高质量发展和新质生产力有什么新闻？"),
            _msg("assistant", "有相关报道。[news:jjrb:abc123]"),
            _msg("user", "那它呢？"),
        ]
        context = build_session_context(history)

        expanded = build_contextual_retrieval_query("那它呢？", context)

        self.assertIn("高质量发展", expanded)
        self.assertIn("新质生产力", expanded)
        self.assertIn("那它呢", expanded)

    def test_source_directive_zhi_kan_removed_but_source_name_kept(self):
        context = build_session_context([])

        cleaned = build_contextual_retrieval_query(
            "只看经济日报，新质生产力如何影响制造业？",
            context,
        )

        self.assertNotIn("只看", cleaned)
        self.assertIn("经济日报", cleaned)
        self.assertIn("新质生产力", cleaned)
        self.assertIn("制造业", cleaned)

    def test_synthesis_directive_cleaned_from_multi_doc_query(self):
        context = build_session_context([])

        cleaned = build_contextual_retrieval_query(
            "请综合说明新质生产力、科技创新和产业升级之间的关系。",
            context,
        )

        self.assertNotIn("请", cleaned)
        self.assertNotIn("综合说明", cleaned)
        self.assertIn("新质生产力", cleaned)
        self.assertIn("科技创新", cleaned)
        self.assertIn("产业升级", cleaned)

    def test_industrial_chain_recognized_as_topic(self):
        history = [
            _msg("user", "新质生产力对制造业、产业链、科技创新分别有什么影响？"),
        ]
        context = build_session_context(history)

        self.assertIn("产业链", context.session_summary["confirmed_topics"])

    def test_contextual_follow_up_uses_short_term_article_anchor(self):
        history = [
            _msg("user", "科技保险为创新减震这篇报道讲了什么？"),
            _msg("assistant", "有相关报道。[news:jjrb:af17afe835290422]"),
            _msg("user", "这个对科技企业风险保障有什么作用？"),
        ]
        context = build_session_context(history)

        expanded = build_contextual_retrieval_query("这个对科技企业风险保障有什么作用？", context)

        self.assertIn("科技保险为创新减震", expanded)
        self.assertIn("科技企业风险保障", expanded)
        self.assertIn("报道", expanded)
        self.assertIn("news:jjrb:af17afe835290422", context.last_evidence_ids)
        self.assertFalse(context.memory_is_evidence)

    def test_plural_contextual_follow_up_uses_short_term_article_anchor(self):
        history = [
            _msg("user", "制造业六化转型再提速这篇报道讲了什么？"),
            _msg("assistant", "有相关报道。[news:jjrb:ac7e8fcf5dfa6a03]"),
            _msg("user", "这些转型对现代化产业体系有什么意义？"),
        ]
        context = build_session_context(history)

        expanded = build_contextual_retrieval_query("这些转型对现代化产业体系有什么意义？", context)

        self.assertIn("制造业六化转型再提速", expanded)
        self.assertIn("现代化产业体系", expanded)
        self.assertIn("报道", expanded)

    def test_general_chat_does_not_force_citation(self):
        contract = build_answer_contract(understand_user_query("你好，介绍一下你自己"), intent="general_chat")

        self.assertFalse(contract.requires_evidence)
        self.assertFalse(contract.must_include_citations)

    def test_news_question_still_requires_evidence(self):
        contract = build_answer_contract(understand_user_query("最近财政政策有什么新闻？"), intent="news_qa")

        self.assertTrue(contract.requires_evidence)
        self.assertTrue(contract.must_include_citations)


if __name__ == "__main__":
    unittest.main()
