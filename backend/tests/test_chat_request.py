import unittest

from pydantic import ValidationError

from agent.config.ai_conf import settings
from backend.app.schemas.ai import ChatRequest


class ChatRequestTests(unittest.TestCase):
    def test_message_is_trimmed(self):
        self.assertEqual(ChatRequest(message="  新质生产力有什么新闻？ \n").message, "新质生产力有什么新闻？")

    def test_blank_and_oversized_messages_are_rejected(self):
        for message in ("", "   \n\t", "字" * (settings.ai_chat_max_message_chars + 1)):
            with self.assertRaises(ValidationError):
                ChatRequest(message=message)
        ChatRequest(message="字" * settings.ai_chat_max_message_chars)

    def test_session_id_must_be_positive(self):
        self.assertEqual(ChatRequest(message="hi", sessionId=3).session_id, 3)
        with self.assertRaises(ValidationError):
            ChatRequest(message="hi", sessionId=0)


if __name__ == "__main__":
    unittest.main()
