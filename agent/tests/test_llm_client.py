import unittest
from types import SimpleNamespace

import asyncio
import dataclasses
import types
from unittest import mock

from agent.harness import llm_client
from agent.harness.llm_client import build_chat_completion_kwargs, extract_stream_content


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

    def test_enable_thinking_style_for_siliconflow(self):
        kwargs = build_chat_completion_kwargs(model="m", messages=[], stream=False,
                                              thinking_enabled=True, thinking_style="enable_thinking")
        self.assertEqual(kwargs["extra_body"], {"enable_thinking": True})


class _Status(Exception):
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code


class _FakeOpenAI:
    def __init__(self, name, error=None):
        self.name, self.error, self.calls = name, error, []
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        message = types.SimpleNamespace(content=f"answer from {self.name}")
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


class FallbackTests(unittest.TestCase):
    def _client(self, primary_error=None):
        llm_client._primary_exhausted_until = 0.0
        client = llm_client.LLMClient.__new__(llm_client.LLMClient)
        client._client = _FakeOpenAI("deepseek", primary_error)
        client._fallback_client = _FakeOpenAI("siliconflow")
        client.model = client.last_model = "deepseek-flash"
        return client

    def test_exhausted_balance_switches_to_fallback_and_stays_there(self):
        settings = dataclasses.replace(llm_client.settings, llm_fallback_model="deepseek-ai/DeepSeek-V4.1-Flash",
                                       llm_fallback_thinking_enabled=True, llm_fallback_thinking_style="enable_thinking")
        with mock.patch.object(llm_client, "settings", settings):
            client = self._client(_Status(402, "Insufficient Balance"))
            answer = asyncio.run(client.complete([{"role": "user", "content": "hi"}]))
            again = asyncio.run(client.complete([{"role": "user", "content": "hi"}]))

        self.assertEqual((answer, again), ("answer from siliconflow", "answer from siliconflow"))
        self.assertEqual(len(client._client.calls), 1)  # cooldown: the second call skips the primary
        self.assertEqual(client._fallback_client.calls[0]["extra_body"], {"enable_thinking": True})
        self.assertEqual(client.last_model, "deepseek-ai/DeepSeek-V4.1-Flash")

    def test_other_errors_are_not_masked_by_the_fallback(self):
        client = self._client(_Status(400, "invalid request"))
        with self.assertRaises(_Status):
            asyncio.run(client.complete([{"role": "user", "content": "hi"}]))
        self.assertEqual(client._fallback_client.calls, [])
        llm_client._primary_exhausted_until = 0.0


if __name__ == "__main__":
    unittest.main()
