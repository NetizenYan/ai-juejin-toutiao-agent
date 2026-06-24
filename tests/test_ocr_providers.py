import asyncio
import unittest

from harness.external_evidence import ingest_url_via_ocr
from harness.ocr_providers import OCRResult, PaddleOCRProvider, UnlimitedOCRProvider, create_ocr_provider


class OcrProviderTests(unittest.TestCase):
    def test_paddle_provider_normalizes_text_lines_confidence_and_title(self):
        instances = []

        class FakePaddleOCR:
            def __init__(self):
                self.calls = []

            def ocr(self, image_path, cls=True):
                self.calls.append((image_path, cls))
                return [
                    [
                        [[[0, 0], [10, 0], [10, 10], [0, 10]], ("Screenshot Headline", 0.91)],
                        [[[0, 20], [10, 20], [10, 30], [0, 30]], ("Body paragraph", 0.83)],
                    ]
                ]

        def fake_factory(**kwargs):
            instances.append((kwargs, FakePaddleOCR()))
            return instances[-1][1]

        provider = PaddleOCRProvider(factory=fake_factory, lang="ch", use_angle_cls=True)

        result = asyncio.run(provider.extract("captures/page.png"))

        self.assertEqual(instances[0][0]["lang"], "ch")
        self.assertEqual(instances[0][1].calls, [("captures/page.png", True)])
        self.assertEqual(result.engine, "paddleocr")
        self.assertEqual(result.text, "Screenshot Headline\nBody paragraph")
        self.assertEqual(result.title, "Screenshot Headline")
        self.assertAlmostEqual(result.confidence, 0.87)
        self.assertEqual(len(result.lines), 2)

    def test_paddle_provider_normalizes_v3_predict_result(self):
        instances = []

        class FakePaddleOCRV3:
            def __init__(self):
                self.calls = []

            def predict(self, image_path):
                self.calls.append(image_path)
                return [
                    {
                        "res": {
                            "rec_texts": ["新质生产力政策信号", "来自截图OCR的正文"],
                            "rec_scores": [0.96, 0.84],
                            "rec_polys": [
                                [[0, 0], [120, 0], [120, 24], [0, 24]],
                                [[0, 36], [160, 36], [160, 60], [0, 60]],
                            ],
                        }
                    }
                ]

        def fake_factory(**kwargs):
            instances.append((kwargs, FakePaddleOCRV3()))
            return instances[-1][1]

        provider = PaddleOCRProvider(factory=fake_factory, lang="ch", use_angle_cls=False)

        result = asyncio.run(provider.extract("captures/v3-page.png"))

        self.assertEqual(instances[0][1].calls, ["captures/v3-page.png"])
        self.assertEqual(result.text, "新质生产力政策信号\n来自截图OCR的正文")
        self.assertEqual(result.title, "新质生产力政策信号")
        self.assertAlmostEqual(result.confidence, 0.90)
        self.assertEqual(result.lines[0]["box"], [[0, 0], [120, 0], [120, 24], [0, 24]])

    def test_paddle_provider_omits_legacy_angle_cls_when_v3_orientation_is_set(self):
        captured_kwargs = []

        class FakePaddleOCRV3:
            def predict(self, _image_path):
                return [{"res": {"rec_texts": ["ok"], "rec_scores": [0.9]}}]

        def fake_factory(**kwargs):
            captured_kwargs.append(kwargs)
            return FakePaddleOCRV3()

        provider = PaddleOCRProvider(
            factory=fake_factory,
            lang="ch",
            use_angle_cls=False,
            use_textline_orientation=False,
        )

        asyncio.run(provider.extract("captures/v3-page.png"))

        self.assertNotIn("use_angle_cls", captured_kwargs[0])
        self.assertIn("use_textline_orientation", captured_kwargs[0])

    def test_paddle_provider_prefers_predict_when_available(self):
        calls = []

        class FakePaddleOCRCompat:
            def predict(self, image_path):
                calls.append(("predict", image_path))
                return [{"res": {"rec_texts": ["predict ok"], "rec_scores": [0.9]}}]

            def ocr(self, image_path, cls=True):
                calls.append(("ocr", image_path, cls))
                return []

        provider = PaddleOCRProvider(factory=lambda **_: FakePaddleOCRCompat(), lang="ch")

        result = asyncio.run(provider.extract("captures/compat-page.png"))

        self.assertEqual(calls, [("predict", "captures/compat-page.png")])
        self.assertEqual(result.text, "predict ok")

    def test_paddle_provider_converts_array_like_boxes_to_json_safe_lists(self):
        class ArrayLikeBox:
            def tolist(self):
                return [[0, 0], [10, 0], [10, 10], [0, 10]]

        class FakePaddleOCRV3:
            def predict(self, _image_path):
                return [
                    {
                        "res": {
                            "rec_texts": ["json safe"],
                            "rec_scores": [0.88],
                            "rec_polys": [ArrayLikeBox()],
                        }
                    }
                ]

        provider = PaddleOCRProvider(factory=lambda **_: FakePaddleOCRV3(), lang="ch")

        result = asyncio.run(provider.extract("captures/array-box.png"))

        self.assertEqual(result.lines[0]["box"], [[0, 0], [10, 0], [10, 10], [0, 10]])

    def test_ingest_url_via_ocr_accepts_provider_and_preserves_engine_metadata(self):
        indexed_docs = []
        case = self

        class FixedProvider:
            async def extract(self, image_path):
                case.assertEqual(image_path, "captures/x-post.png")
                return OCRResult(
                    text="External screenshot policy signal",
                    confidence=0.78,
                    title="External Screenshot",
                    engine="paddleocr",
                    lines=[
                        {"text": "External screenshot policy signal", "confidence": 0.78},
                    ],
                )

        async def fake_capture_screenshot(_url):
            return {
                "image_path": "captures/x-post.png",
                "raw_image_hash": "sha256:image",
                "captured_at": "2026-06-24T12:00:00Z",
            }

        async def fake_add_external_doc(**kwargs):
            indexed_docs.append(kwargs)
            return 321

        item = asyncio.run(
            ingest_url_via_ocr(
                "https://x.example/post/ocr",
                source_name="X",
                capture_screenshot_fn=fake_capture_screenshot,
                ocr_provider=FixedProvider(),
                add_external_doc_fn=fake_add_external_doc,
            )
        )

        self.assertEqual(indexed_docs[0]["title"], "External Screenshot")
        self.assertEqual(indexed_docs[0]["text"], "External screenshot policy signal")
        self.assertEqual(item["id"], 321)
        self.assertEqual(item["ocr_engine"], "paddleocr")
        self.assertEqual(item["ocr_confidence"], 0.78)
        self.assertEqual(item["acquisition_method"], "ocr_screenshot")
        self.assertEqual(item["verification_status"], "unverified")

    def test_create_provider_keeps_unlimited_ocr_as_explicit_future_provider(self):
        self.assertIsInstance(create_ocr_provider("paddleocr"), PaddleOCRProvider)
        provider = create_ocr_provider("unlimited_ocr")
        self.assertIsInstance(provider, UnlimitedOCRProvider)

        with self.assertRaisesRegex(RuntimeError, "not configured"):
            asyncio.run(provider.extract("captures/long-page.png"))


if __name__ == "__main__":
    unittest.main()
