import asyncio
import hashlib
import unittest

from harness.anchor_resolver import resolve_anchor_candidates
from harness.external_evidence import (
    OcrCaptureRecord,
    denoise_ocr_text,
    index_ocr_capture_record,
    ingest_url_via_ocr,
    verify_external_evidence,
)


class ExternalEvidenceTests(unittest.TestCase):
    def test_ocr_capture_record_exports_low_credibility_candidate_item(self):
        record = OcrCaptureRecord(
            source_url="https://x.example/post/1",
            source_name="X",
            captured_at="2026-06-24T12:00:00Z",
            image_path="captures/x-post-1.png",
            raw_image_hash="sha256:abc123",
            ocr_text="网传新质生产力相关消息。",
            ocr_confidence=0.82,
        )

        item = record.to_candidate_item()

        self.assertEqual(item["source_url"], "https://x.example/post/1")
        self.assertEqual(item["source"], "X")
        self.assertEqual(item["acquisition_method"], "ocr_screenshot")
        self.assertEqual(item["source_credibility"], "low")
        self.assertEqual(item["verification_status"], "unverified")
        self.assertEqual(item["ingest_status"], "pending")
        self.assertEqual(item["raw_image_hash"], "sha256:abc123")
        self.assertEqual(item["ocr_confidence"], 0.82)

    def test_ocr_candidate_can_be_confirmed_but_remains_low_credibility(self):
        record = OcrCaptureRecord(
            source_url="https://x.example/post/1",
            source_name="X",
            captured_at="2026-06-24T12:00:00Z",
            image_path="captures/x-post-1.png",
            raw_image_hash="sha256:abc123",
            ocr_text="网传新质生产力相关消息。",
            ocr_confidence=0.82,
        )

        resolution = resolve_anchor_candidates(
            "我记得X上有一条关于新质生产力的新闻",
            [record.to_candidate_item()],
            source_policy="local_test",
        )

        self.assertEqual(len(resolution.candidates), 1)
        self.assertEqual(resolution.candidates[0].source_credibility, "low")
        self.assertEqual(resolution.candidates[0].acquisition_method, "ocr_screenshot")

    def test_index_ocr_capture_record_preserves_low_credibility_metadata(self):
        calls = []

        async def fake_add_external_doc(**kwargs):
            calls.append(kwargs)
            return 123

        record = OcrCaptureRecord(
            source_url="https://x.example/post/1",
            source_name="X",
            captured_at="2026-06-24T12:00:00Z",
            image_path="captures/x-post-1.png",
            raw_image_hash="sha256:abc123",
            title="External OCR Lead",
            ocr_text="Policy signal from an OCR-only external post.",
            ocr_confidence=0.82,
        )

        item = asyncio.run(index_ocr_capture_record(record, add_external_doc_fn=fake_add_external_doc))

        self.assertEqual(calls[0]["title"], "External OCR Lead")
        self.assertEqual(calls[0]["text"], "Policy signal from an OCR-only external post.")
        self.assertEqual(calls[0]["source"], "external_ocr:X")
        self.assertEqual(calls[0]["url"], "https://x.example/post/1")
        self.assertEqual(item["id"], 123)
        self.assertEqual(item["evidence_id"], "news:123")
        self.assertEqual(item["source_credibility"], "low")
        self.assertEqual(item["verification_status"], "unverified")
        self.assertEqual(item["ingest_status"], "indexed")
        self.assertEqual(item["acquisition_method"], "ocr_screenshot")

    def test_denoise_ocr_text_removes_ui_noise_and_duplicate_lines(self):
        raw_text = "\n".join(
            [
                "Cookie settings",
                "Sign in",
                "Policy signal: new manufacturing funds may expand.",
                "Policy signal: new manufacturing funds may expand.",
                "Share",
                "Advanced manufacturing investment remains the main topic.",
                "&&&&",
                "Related articles",
            ]
        )

        result = denoise_ocr_text(raw_text, max_chars=220, min_signal_chars=20)

        self.assertEqual(result.status, "cleaned")
        self.assertIn("Policy signal: new manufacturing funds may expand.", result.clean_text)
        self.assertIn("Advanced manufacturing investment remains the main topic.", result.clean_text)
        self.assertNotIn("Cookie settings", result.clean_text)
        self.assertNotIn("Sign in", result.clean_text)
        self.assertEqual(result.duplicate_line_count, 1)
        self.assertGreaterEqual(result.removed_line_count, 4)
        self.assertFalse(result.truncated)

    def test_denoise_ocr_text_applies_max_clean_chars(self):
        result = denoise_ocr_text("A" * 120, max_chars=30, min_signal_chars=5)

        self.assertEqual(result.status, "cleaned")
        self.assertEqual(result.clean_text, "A" * 30)
        self.assertTrue(result.truncated)

    def test_ingest_url_via_ocr_indexes_clean_text_with_staging_metadata(self):
        indexed_docs = []
        raw_text = "\n".join(
            [
                "Cookie settings",
                "Policy signal: funding support expands.",
                "Policy signal: funding support expands.",
                "Share",
                "Advanced manufacturing remains central.",
            ]
        )
        expected_clean = "Policy signal: funding support expands.\nAdvanced manufacturing remains central."

        async def fake_capture_screenshot(_url):
            return {
                "image_path": "captures/x-post-clean.png",
                "raw_image_hash": "sha256:clean",
                "captured_at": "2026-06-24T12:00:00Z",
            }

        async def fake_extract_ocr_text(_image_path):
            return {"text": raw_text, "confidence": 0.91, "title": "Clean OCR Lead"}

        async def fake_add_external_doc(**kwargs):
            indexed_docs.append(kwargs)
            return 321

        item = asyncio.run(
            ingest_url_via_ocr(
                "https://x.example/post/clean",
                source_name="X",
                capture_screenshot_fn=fake_capture_screenshot,
                extract_ocr_text_fn=fake_extract_ocr_text,
                add_external_doc_fn=fake_add_external_doc,
            )
        )

        self.assertEqual(indexed_docs[0]["text"], expected_clean)
        self.assertEqual(item["text"], expected_clean)
        self.assertEqual(item["raw_ocr_text_hash"], "sha256:" + hashlib.sha256(raw_text.encode("utf-8")).hexdigest())
        self.assertEqual(item["raw_ocr_text_chars"], len(raw_text))
        self.assertEqual(item["clean_ocr_text_chars"], len(expected_clean))
        self.assertEqual(item["duplicate_ocr_line_count"], 1)
        self.assertGreaterEqual(item["denoise_removed_line_count"], 2)
        self.assertEqual(item["ocr_denoise_status"], "cleaned")
        self.assertEqual(item["staging_status"], "staged_clean")
        self.assertEqual(item["ingest_status"], "indexed")

    def test_ingest_url_via_ocr_rejects_high_confidence_noise_after_denoise(self):
        indexed_docs = []
        raw_text = "\n".join(["Cookie settings", "Sign in", "Share", "&&&&"])

        async def fake_capture_screenshot(_url):
            return {
                "image_path": "captures/x-post-noise.png",
                "raw_image_hash": "sha256:noise",
                "captured_at": "2026-06-24T12:00:00Z",
            }

        async def fake_extract_ocr_text(_image_path):
            return {"text": raw_text, "confidence": 0.94}

        async def fake_add_external_doc(**kwargs):
            indexed_docs.append(kwargs)
            return 654

        item = asyncio.run(
            ingest_url_via_ocr(
                "https://x.example/post/noise",
                source_name="X",
                capture_screenshot_fn=fake_capture_screenshot,
                extract_ocr_text_fn=fake_extract_ocr_text,
                add_external_doc_fn=fake_add_external_doc,
                min_ocr_confidence=0.35,
            )
        )

        self.assertEqual(indexed_docs, [])
        self.assertEqual(item["ingest_status"], "rejected_noisy_ocr")
        self.assertEqual(item["ocr_denoise_status"], "rejected_no_signal")
        self.assertEqual(item["staging_status"], "staged_rejected")
        self.assertEqual(item["raw_ocr_text_hash"], "sha256:" + hashlib.sha256(raw_text.encode("utf-8")).hexdigest())

    def test_verify_external_evidence_marks_station_matched_but_keeps_source_low_trust(self):
        ocr_item = {
            "title": "External OCR Lead",
            "text": "Policy signal says advanced manufacturing support funds will expand.",
            "source": "X",
            "source_credibility": "low",
        }
        station_items = [{
            "id": 10,
            "evidence_id": "news:10",
            "title": "Policy signal for advanced manufacturing",
            "summary": "Station report says manufacturing support funds expand.",
            "source": "Economic Daily",
        }]

        verification = verify_external_evidence(ocr_item, station_items, min_overlap_terms=2)
        metadata = verification.as_metadata()

        self.assertEqual(metadata["verification_status"], "station_matched")
        self.assertTrue(metadata["matched"])
        self.assertEqual(metadata["matched_station_evidence_ids"], ["news:10"])
        self.assertIn("advanced", metadata["overlap_terms"])
        self.assertIn("manufacturing", metadata["overlap_terms"])
        self.assertIn("站内", metadata["verification_reason"])
        self.assertIn("X", metadata["user_warning"])
        self.assertEqual(ocr_item["source_credibility"], "low")

    def test_verify_external_evidence_rejects_low_signal_ocr_text_before_matching(self):
        verification = verify_external_evidence(
            {"text": "ok", "source": "X"},
            [{"id": 10, "title": "ok policy", "summary": "ok"}],
            min_overlap_terms=2,
        )

        self.assertEqual(verification.verification_status, "low_signal")
        self.assertFalse(verification.matched)
        self.assertEqual(verification.matched_station_evidence_ids, [])

    def test_verify_external_evidence_stays_unverified_when_station_terms_do_not_match(self):
        verification = verify_external_evidence(
            {"title": "External OCR", "text": "Advanced manufacturing support funds expand.", "source": "X"},
            [{"id": 10, "title": "Sports result", "summary": "Team won the game."}],
            min_overlap_terms=2,
        )

        self.assertEqual(verification.verification_status, "unverified")
        self.assertFalse(verification.matched)
        self.assertEqual(verification.matched_station_evidence_ids, [])

    def test_ingest_url_via_ocr_captures_text_and_indexes_low_credibility_record(self):
        captures = []
        indexed_docs = []

        async def fake_capture_screenshot(url):
            captures.append(url)
            return {
                "image_path": "captures/x-post-1.png",
                "raw_image_hash": "sha256:abc123",
                "captured_at": "2026-06-24T12:00:00Z",
            }

        async def fake_extract_ocr_text(image_path):
            self.assertEqual(image_path, "captures/x-post-1.png")
            return {
                "text": "网传新质生产力相关政策线索。",
                "confidence": 0.86,
                "title": "X OCR Lead",
            }

        async def fake_add_external_doc(**kwargs):
            indexed_docs.append(kwargs)
            return 456

        item = asyncio.run(
            ingest_url_via_ocr(
                "https://x.example/post/1",
                source_name="X",
                capture_screenshot_fn=fake_capture_screenshot,
                extract_ocr_text_fn=fake_extract_ocr_text,
                add_external_doc_fn=fake_add_external_doc,
            )
        )

        self.assertEqual(captures, ["https://x.example/post/1"])
        self.assertEqual(indexed_docs[0]["title"], "X OCR Lead")
        self.assertEqual(indexed_docs[0]["text"], "网传新质生产力相关政策线索。")
        self.assertEqual(indexed_docs[0]["source"], "external_ocr:X")
        self.assertEqual(item["id"], 456)
        self.assertEqual(item["source_url"], "https://x.example/post/1")
        self.assertEqual(item["raw_image_hash"], "sha256:abc123")
        self.assertEqual(item["ocr_confidence"], 0.86)
        self.assertEqual(item["source_credibility"], "low")
        self.assertEqual(item["verification_status"], "unverified")
        self.assertEqual(item["acquisition_method"], "ocr_screenshot")
        self.assertEqual(item["ingest_status"], "indexed")

    def test_ingest_url_via_ocr_rejects_low_confidence_text_without_indexing(self):
        indexed_docs = []

        async def fake_capture_screenshot(_url):
            return {
                "image_path": "captures/x-post-weak.png",
                "raw_image_hash": "sha256:weak",
                "captured_at": "2026-06-24T12:00:00Z",
            }

        async def fake_extract_ocr_text(_image_path):
            return {"text": "疑似政策", "confidence": 0.12}

        async def fake_add_external_doc(**kwargs):
            indexed_docs.append(kwargs)
            return 789

        item = asyncio.run(
            ingest_url_via_ocr(
                "https://x.example/post/weak",
                source_name="X",
                capture_screenshot_fn=fake_capture_screenshot,
                extract_ocr_text_fn=fake_extract_ocr_text,
                add_external_doc_fn=fake_add_external_doc,
                min_ocr_confidence=0.35,
            )
        )

        self.assertEqual(indexed_docs, [])
        self.assertEqual(item["id"], "https://x.example/post/weak")
        self.assertEqual(item["ingest_status"], "rejected")
        self.assertEqual(item["source_credibility"], "low")
        self.assertEqual(item["verification_status"], "unverified")
        self.assertEqual(item["acquisition_method"], "ocr_screenshot")


if __name__ == "__main__":
    unittest.main()
