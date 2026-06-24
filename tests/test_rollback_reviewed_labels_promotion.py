import json
import tempfile
import unittest
from pathlib import Path


class RollbackReviewedLabelsPromotionTests(unittest.TestCase):
    def _write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def test_refuses_without_exact_confirmation_token(self):
        try:
            from scripts.rollback_reviewed_labels_promotion import rollback_reviewed_labels_promotion
        except ModuleNotFoundError:
            self.fail("scripts.rollback_reviewed_labels_promotion should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            official = root / "official.jsonl"
            backup = root / "backup.jsonl"
            apply_report = root / "apply.json"
            rollback_dir = root / "rollback_backups"
            official.write_text("new\n", encoding="utf-8")
            backup.write_text("old\n", encoding="utf-8")
            self._write_json(
                apply_report,
                {"applied": True, "backup": {"created": True, "path": str(backup)}},
            )
            before = official.read_text(encoding="utf-8")

            result = rollback_reviewed_labels_promotion(
                apply_report,
                official,
                rollback_dir,
                confirm="wrong-token",
            )
            after = official.read_text(encoding="utf-8")

        self.assertFalse(result["rolled_back"])
        self.assertIn("confirmation token mismatch", result["blockers"])
        self.assertEqual(before, after)
        self.assertFalse(result["current_backup"]["created"])

    def test_refuses_when_apply_report_was_not_applied(self):
        try:
            from scripts.rollback_reviewed_labels_promotion import (
                ROLLBACK_CONFIRMATION_TOKEN,
                rollback_reviewed_labels_promotion,
            )
        except ModuleNotFoundError:
            self.fail("scripts.rollback_reviewed_labels_promotion should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            official = root / "official.jsonl"
            apply_report = root / "apply.json"
            rollback_dir = root / "rollback_backups"
            official.write_text("current\n", encoding="utf-8")
            self._write_json(
                apply_report,
                {"applied": False, "backup": {"created": False, "path": None}},
            )

            result = rollback_reviewed_labels_promotion(
                apply_report,
                official,
                rollback_dir,
                confirm=ROLLBACK_CONFIRMATION_TOKEN,
            )

        self.assertFalse(result["rolled_back"])
        self.assertIn("apply report was not applied", result["blockers"])

    def test_rolls_back_from_apply_backup_with_exact_confirmation_token(self):
        try:
            from scripts.rollback_reviewed_labels_promotion import (
                ROLLBACK_CONFIRMATION_TOKEN,
                rollback_reviewed_labels_promotion,
            )
        except ModuleNotFoundError:
            self.fail("scripts.rollback_reviewed_labels_promotion should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            official = root / "official.jsonl"
            backup = root / "backup.jsonl"
            apply_report = root / "apply.json"
            rollback_dir = root / "rollback_backups"
            official.write_text("new\n", encoding="utf-8")
            backup.write_text("old\n", encoding="utf-8")
            self._write_json(
                apply_report,
                {"applied": True, "backup": {"created": True, "path": str(backup)}},
            )

            result = rollback_reviewed_labels_promotion(
                apply_report,
                official,
                rollback_dir,
                confirm=ROLLBACK_CONFIRMATION_TOKEN,
            )
            after = official.read_text(encoding="utf-8")
            current_backup_text = Path(result["current_backup"]["path"]).read_text(encoding="utf-8")

        self.assertTrue(result["rolled_back"])
        self.assertEqual(after, "old\n")
        self.assertEqual(current_backup_text, "new\n")
        self.assertTrue(result["current_backup"]["created"])

    def test_write_rollback_report_outputs_files(self):
        try:
            from scripts.rollback_reviewed_labels_promotion import write_rollback_report
        except ModuleNotFoundError:
            self.fail("scripts.rollback_reviewed_labels_promotion should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            official = root / "official.jsonl"
            apply_report = root / "apply.json"
            rollback_dir = root / "rollback_backups"
            report = root / "rollback.md"
            json_report = root / "rollback.json"
            official.write_text("current\n", encoding="utf-8")
            self._write_json(apply_report, {"applied": False, "backup": {"created": False, "path": None}})

            result = write_rollback_report(
                apply_report,
                official,
                rollback_dir,
                report,
                json_report,
                confirm="wrong-token",
            )
            report_text = report.read_text(encoding="utf-8")
            json_report_exists = json_report.exists()

        self.assertFalse(result["rolled_back"])
        self.assertIn("Rollback", report_text)
        self.assertTrue(json_report_exists)
