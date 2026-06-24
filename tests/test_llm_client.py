import unittest
from types import SimpleNamespace

from harness.llm_client import build_chat_completion_kwargs, extract_stream_content


class LLMClientConfigTests(unittest.TestCase):
    def test_builds_deepseek_thinking_kwargs(self):
        kwargs = build_chat_completion_kwargs(
            model="deepseek-v4-pro",
            messages=[{"role": "user", "content": "Hello"}],
            stream=False,
            reasoning_effort="high",
            thinking_enabled=True,
        )

        self.assertEqual(kwargs["model"], "deepseek-v4-pro")
        self.assertEqual(kwargs["reasoning_effort"], "high")
        self.assertEqual(kwargs["extra_body"], {"thinking": {"type": "enabled"}})

    def test_does_not_add_optional_kwargs_when_disabled(self):
        kwargs = build_chat_completion_kwargs(
            model="qwen3.5:9b",
            messages=[{"role": "user", "content": "Hello"}],
            stream=True,
            reasoning_effort="",
            thinking_enabled=False,
        )

        self.assertNotIn("reasoning_effort", kwargs)
        self.assertNotIn("extra_body", kwargs)

    def test_stream_content_filters_provider_reasoning_fields(self):
        reasoning_only = SimpleNamespace(
            content=None,
            reasoning_content="hidden chain of thought",
            reasoning="hidden reasoning",
            thinking="hidden thinking",
        )
        final_delta = SimpleNamespace(
            content="OK",
            reasoning_content="hidden chain of thought",
        )

        self.assertEqual(extract_stream_content(reasoning_only), "")
        self.assertEqual(extract_stream_content(final_delta), "OK")


if __name__ == "__main__":
    unittest.main()
