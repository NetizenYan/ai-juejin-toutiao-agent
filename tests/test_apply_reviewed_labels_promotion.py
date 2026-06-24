import json
import tempfile
import unittest
from pathlib import Path


class ApplyReviewedLabelsPromotionTests(unittest.TestCase):
    def _write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
            encoding="utf-8",
        )

    def test_refuses_to_write_without_exact_confirmation_token(self):
        try:
            from scripts.apply_reviewed_labels_promotion import apply_reviewed_labels_promotion
        except ModuleNotFoundError:
            self.fail("scripts.apply_reviewed_labels_promotion should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            preview = root / "preview.jsonl"
            official = root / "official.jsonl"
            backup_dir = root / "backups"
            self._write_jsonl(preview, [{"candidate_id": "candidate_a1", "decision": "merge_with_existing", "notes": "Duplicate."}])
            self._write_jsonl(official, [])
            before = official.read_text(encoding="utf-8")

            result = apply_reviewed_labels_promotion(
                preview,
                official,
                backup_dir,
                confirm="wrong-token",
            )
            after = official.read_text(encoding="utf-8")

        self.assertFalse(result["applied"])
        self.assertIn("confirmation token mismatch", result["blockers"])
        self.assertEqual(before, after)
        self.assertFalse(result["backup"]["created"])

    def test_applies_with_exact_confirmation_token_and_creates_backup(self):
        try:
            from scripts.apply_reviewed_labels_promotion import (
                CONFIRMATION_TOKEN,
                apply_reviewed_labels_promotion,
            )
        except ModuleNotFoundError:
            self.fail("scripts.apply_reviewed_labels_promotion should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            preview = root / "preview.jsonl"
            official = root / "official.jsonl"
            backup_dir = root / "backups"
            preview_rows = [
                {
                    "candidate_id": "candidate_a1",
                    "decision": "merge_with_existing",
                    "existing_gold_id": "a1",
                    "case_type": "A_exact_news_qa",
                    "notes": "Duplicate.",
                }
            ]
            self._write_jsonl(preview, preview_rows)
            self._write_jsonl(official, [])
            before = official.read_text(encoding="utf-8")

            result = apply_reviewed_labels_promotion(
                preview,
                official,
                backup_dir,
                confirm=CONFIRMATION_TOKEN,
            )

            official_text = official.read_text(encoding="utf-8")
            preview_text = preview.read_text(encoding="utf-8")
            backup_path = Path(result["backup"]["path"])
            backup_text = backup_path.read_text(encoding="utf-8")

        self.assertTrue(result["applied"])
        self.assertEqual(result["official_after"]["row_count"], 1)
        self.assertEqual(official_text, preview_text)
        self.assertEqual(backup_text, before)
        self.assertTrue(result["backup"]["created"])

    def test_blocks_nonempty_official_by_default(self):
        try:
            from scripts.apply_reviewed_labels_promotion import (
                CONFIRMATION_TOKEN,
                apply_reviewed_labels_promotion,
            )
        except ModuleNotFoundError:
            self.fail("scripts.apply_reviewed_labels_promotion should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            preview = root / "preview.jsonl"
            official = root / "official.jsonl"
            backup_dir = root / "backups"
            self._write_jsonl(preview, [{"candidate_id": "candidate_a1", "decision": "merge_with_existing", "notes": "Duplicate."}])
            self._write_jsonl(official, [{"candidate_id": "candidate_old", "decision": "reject", "notes": "Old."}])
            before = official.read_text(encoding="utf-8")

            result = apply_reviewed_labels_promotion(
                preview,
                official,
                backup_dir,
                confirm=CONFIRMATION_TOKEN,
            )

            after = official.read_text(encoding="utf-8")

        self.assertFalse(result["applied"])
        self.assertIn("official reviewed-label file already has rows", result["blockers"])
        self.assertEqual(before, after)
