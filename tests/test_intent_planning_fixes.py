import asyncio
import dataclasses
import unittest
from types import SimpleNamespace
from unittest import mock

from harness import agent
from harness.intent import MAX_RETRIEVAL_QUERY_CHARS, build_fallback_tool_calls, detect_intent


def _tool_message(name: str, arguments: str):
    return SimpleNamespace(tool_calls=[SimpleNamespace(function=SimpleNamespace(name=name, arguments=arguments))])


class _PlanningClient:
    def __init__(self, message=None, error: Exception | None = None):
        self.message = message
        self.error = error
        self.calls = 0

    async def complete_message(self, *_args, **_kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return self.message


_RETRIEVE_DEFS = [{"type": "function", "function": {"name": "retrieve_news", "parameters": {}}}]


def _plan(client, query, allowed=frozenset({"retrieve_news"}), tool_defs=_RETRIEVE_DEFS):
    history = [{"role": "user", "content": query}]
    return asyncio.run(agent._plan_tool_calls(client, history, query, tool_defs, set(allowed), 1))


class IntentKeywordTests(unittest.TestCase):
    def test_ascii_keyword_requires_word_boundary(self):
        self.assertEqual(detect_intent("什么是email"), "general_chat")
        self.assertEqual(detect_intent("detail 怎么翻译"), "general_chat")
        self.assertEqual(detect_intent("最近有什么AI新闻可以看？"), "news_qa")
        self.assertEqual(detect_intent("AI芯片怎么样"), "news_qa")

    def test_explicit_news_id_routes_to_news_lookup(self):
        self.assertEqual(detect_intent("新闻 123 讲了什么"), "news_lookup")
        self.assertEqual(detect_intent("帮我看看文章#88"), "news_lookup")
        calls = build_fallback_tool_calls("新闻 123 讲了什么", user_id=1)
        self.assertEqual(calls, [{"name": "news_detail", "arguments": {"news_id": 123}}])
        self.assertIn("news_detail", agent.ALLOWED_TOOLS_BY_INTENT["news_lookup"])
        self.assertIs(agent._SESSION_BY_INTENT["news_lookup"], agent.business_session)

    def test_dates_and_counts_are_not_news_ids(self):
        self.assertEqual(detect_intent("新闻 2026年经济形势"), "news_qa")
        self.assertEqual(detect_intent("给我新闻 5 条"), "news_qa")


class ToolPlanningTests(unittest.TestCase):
    def test_news_lookup_fallback_survives_whitelist(self):
        calls = _plan(_PlanningClient(error=RuntimeError("down")), "新闻 123 讲了什么",
                      allowed={"news_detail"}, tool_defs=[])
        self.assertEqual(calls, [{"name": "news_detail", "arguments": {"news_id": 123}}])

    def test_long_query_is_clipped_instead_of_dropped(self):
        query = "请总结最近关于新质生产力的新闻，" + "重点关注制造业升级和科技创新，" * 20
        self.assertGreater(len(query), MAX_RETRIEVAL_QUERY_CHARS)
        calls = _plan(_PlanningClient(error=RuntimeError("down")), query, tool_defs=[])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "retrieve_news")
        self.assertLessEqual(len(calls[0]["arguments"]["query"]), MAX_RETRIEVAL_QUERY_CHARS)

    def test_model_planned_call_is_used_first(self):
        client = _PlanningClient(_tool_message("retrieve_news", '{"query": "芯片 产业 新闻"}'))
        calls = _plan(client, "最近芯片有什么新闻")
        self.assertEqual(client.calls, 1)
        self.assertEqual(calls[0]["arguments"]["query"], "芯片 产业 新闻")

    def test_model_failure_falls_back_to_rules(self):
        calls = _plan(_PlanningClient(error=RuntimeError("down")), "最近芯片有什么新闻")
        self.assertEqual(calls[0]["arguments"]["query"], "最近芯片有什么新闻")

    def test_disallowed_model_call_falls_back_to_rules(self):
        client = _PlanningClient(_tool_message("web_fetch", '{"url": "https://example.com"}'))
        calls = _plan(client, "最近芯片有什么新闻")
        self.assertEqual([c["name"] for c in calls], ["retrieve_news"])

    def test_deterministic_mode_skips_model(self):
        client = _PlanningClient(_tool_message("retrieve_news", '{"query": "x"}'))
        rules_only = dataclasses.replace(agent.settings, agent_tool_planning="deterministic")
        with mock.patch.object(agent, "settings", rules_only):
            calls = _plan(client, "最近芯片有什么新闻")
        self.assertEqual(client.calls, 0)
        self.assertEqual(calls[0]["arguments"]["query"], "最近芯片有什么新闻")


if __name__ == "__main__":
    unittest.main()
