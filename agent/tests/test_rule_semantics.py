"""Rule-changing requests in other words are recognised by meaning, ordinary requests are not."""
import asyncio
import unittest
from unittest import mock

from agent.harness import agent, rule_semantics

EXAMPLES = [("drop_citations", [1.0, 0.0, 0.0]), ("memory_rule", [0.0, 1.0, 0.0]), ("ordinary", [0.0, 0.0, 1.0])]
MESSAGES = {
    "删掉每句后面的尾巴": [0.95, 0.0, 0.3],     # close to a request, far from ordinary
    "整理成表格": [0.2, 0.0, 0.98],             # ordinary
    "把出处整理成表格": [0.75, 0.0, 0.70],      # close to both: not caught
    "今天天气": [0.3, 0.3, 0.3],                # close to nothing
}


async def _embed(texts):
    return [MESSAGES[text] for text in texts]


class ClassifyManyTests(unittest.TestCase):
    def setUp(self):
        rule_semantics._cache["examples"] = EXAMPLES
        self.addCleanup(rule_semantics._cache.clear)

    def test_only_a_message_clearly_closer_to_a_request_than_to_ordinary_ones_counts(self):
        # conftest stubs classify_many for the agent tests; the implementation is _classify_many.
        kinds = asyncio.run(rule_semantics._classify_many(list(MESSAGES), _embed))

        self.assertEqual(kinds, ["drop_citations", None, None, None])

    def test_a_broken_embedding_service_means_no_kind(self):
        async def broken(_texts):
            raise ConnectionError("down")

        self.assertEqual(asyncio.run(rule_semantics._classify_many(["删掉每句后面的尾巴"], broken)), [None])


class AgentTests(unittest.TestCase):
    def test_only_messages_the_keywords_miss_are_checked_by_meaning(self):
        seen = []

        async def classify_many(texts, embed=None):
            seen.extend(texts)
            return ["drop_citations" if "尾巴" in text else None for text in texts]

        history = [
            {"role": "user", "content": "以后每次回答都按这个格式来"},          # keyword: memory_rule
            {"role": "assistant", "content": "好的。"},
            {"role": "user", "content": "每句话后面那条小尾巴，这次都处理干净。"},
        ]
        with mock.patch.object(rule_semantics, "classify_many", classify_many):
            kinds = asyncio.run(agent._rule_request_kinds(history[-1]["content"], history))

        self.assertEqual(kinds, ("drop_citations", "memory_rule"))
        self.assertEqual(seen, ["每句话后面那条小尾巴，这次都处理干净。"])


if __name__ == "__main__":
    unittest.main()
