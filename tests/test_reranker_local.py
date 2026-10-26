import asyncio
import os
import subprocess
import sys
import unittest
from unittest import mock

from harness import reranker


class LocalRerankerTests(unittest.TestCase):
    def setUp(self):
        reranker._RERANKER, reranker._LOAD_ERROR = None, None

    def tearDown(self):
        reranker._RERANKER, reranker._LOAD_ERROR = None, None

    def test_importing_the_agent_does_not_force_hugging_face_offline(self):
        env = {k: v for k, v in os.environ.items() if k != "HF_HUB_OFFLINE"}
        out = subprocess.run(
            [sys.executable, "-c", "import os, harness.agent; print(os.environ.get('HF_HUB_OFFLINE'))"],
            capture_output=True, text=True, env=env, check=True,
        )
        self.assertEqual(out.stdout.strip().splitlines()[-1], "None")

    def test_missing_local_model_falls_back_once_without_retrying(self):
        items = [{"title": "a"}, {"title": "b"}]
        with mock.patch.dict(os.environ, {"RERANKER_PROVIDER": ""}), \
                mock.patch.dict(sys.modules, {"sentence_transformers": None}):
            first = asyncio.run(reranker.rerank("q", items, top_k=1))
            error = reranker._LOAD_ERROR
            second = asyncio.run(reranker.rerank("q", items, top_k=1))

        self.assertEqual(first, items[:1])
        self.assertEqual(second, items[:1])
        self.assertIn("local reranker unavailable", error)
        self.assertIs(reranker._LOAD_ERROR, error)  # remembered, not re-attempted


if __name__ == "__main__":
    unittest.main()
