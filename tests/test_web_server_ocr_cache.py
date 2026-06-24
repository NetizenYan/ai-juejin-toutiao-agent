import unittest

from mcp_servers import web_server


class WebServerOcrProviderCacheTests(unittest.TestCase):
    def setUp(self):
        self.original_create = web_server.create_ocr_provider
        web_server._OCR_PROVIDER_CACHE.clear()

    def tearDown(self):
        web_server.create_ocr_provider = self.original_create
        web_server._OCR_PROVIDER_CACHE.clear()

    def test_reuses_ocr_provider_for_same_provider_name(self):
        created = []

        def fake_create_ocr_provider(name):
            provider = object()
            created.append((name, provider))
            return provider

        web_server.create_ocr_provider = fake_create_ocr_provider

        first = web_server._get_ocr_provider("paddleocr")
        second = web_server._get_ocr_provider("paddleocr")

        self.assertIs(first, second)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0][0], "paddleocr")

    def test_uses_separate_cached_provider_for_different_provider_name(self):
        created = []

        def fake_create_ocr_provider(name):
            provider = {"name": name}
            created.append(provider)
            return provider

        web_server.create_ocr_provider = fake_create_ocr_provider

        paddle = web_server._get_ocr_provider("paddleocr")
        unlimited = web_server._get_ocr_provider("unlimited_ocr")
        paddle_again = web_server._get_ocr_provider("paddleocr")

        self.assertIs(paddle, paddle_again)
        self.assertIsNot(paddle, unlimited)
        self.assertEqual([item["name"] for item in created], ["paddleocr", "unlimited_ocr"])


if __name__ == "__main__":
    unittest.main()
