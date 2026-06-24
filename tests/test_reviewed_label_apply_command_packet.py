import json
import tempfile
import unittest
from pathlib import Path


class ReviewedLabelApplyCommandPacketTests(unittest.TestCase):
    def _write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _ready_preflight(self) -> dict:
        return {
            "apply_ready": True,
            "checks": {
                "preview_validation_ok": True,
                "manual_transaction_ready": True,
                "sandbox_simulation_applied": True,
                "sandbox_ready_for_gold_expansion": True,
                "real_official_unchanged": True,
                "tune_script_absent": True,
                "official_train_split_absent": True,
                "official_heldout_split_absent": True,
                "sentence_transformers_absent": True,
            },
            "validation": {"ok": True, "row_count": 80, "accepted_count": 65},
            "promotion_plan": {
                "preview": {
                    "path": "eval/gold/reviewed_labels_official_preview_20260622.jsonl",
                    "sha256": "preview-sha",
                    "row_count": 80,
                },
                "official": {
                    "path": "eval/gold/reviewed_labels_20260622.jsonl",
                    "sha256": "official-sha",
                    "row_count": 0,
                },
            },
            "sandbox": {
                "pipeline_state": {
                    "coverage": {
                        "projected_formal_count": 115,
                        "deficits_after_accepts": {"A_exact_news_qa": 0},
                    }
                }
            },
            "blockers": [],
        }

    def test_packet_includes_guarded_apply_and_post_apply_commands_when_preflight_ready(self):
        try:
            from scripts.render_reviewed_label_apply_command_packet import build_command_packet
        except ModuleNotFoundError:
            self.fail("scripts.render_reviewed_label_apply_command_packet should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            preflight = Path(tmpdir) / "preflight.json"
            self._write_json(preflight, self._ready_preflight())

            packet = build_command_packet(preflight)

        self.assertTrue(packet["packet_ready"])
        self.assertEqual(packet["confirmation_token"], "COPY_REVIEWED_LABELS_20260622")
        self.assertIn("--confirm COPY_REVIEWED_LABELS_20260622", packet["apply_command"])
        post_apply = "\n".join(packet["post_apply_commands"])
        self.assertIn("validate_gold_reviewed_labels.py", post_apply)
        self.assertIn("check_reviewed_label_conditions.py", post_apply)
        self.assertIn("check_reviewed_label_pipeline_state.py", post_apply)
        self.assertIn("report_reviewed_label_coverage.py", post_apply)
        self.assertIn("audit_gold_promotion_readiness.py", post_apply)
        self.assertIn("build_expanded_gold_preview.py", post_apply)
        self.assertIn("check_gold_tuning_gate.py", post_apply)

    def test_packet_blocks_when_preflight_not_ready(self):
        try:
            from scripts.render_reviewed_label_apply_command_packet import build_command_packet
        except ModuleNotFoundError:
            self.fail("scripts.render_reviewed_label_apply_command_packet should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            preflight = Path(tmpdir) / "preflight.json"
            data = self._ready_preflight()
            data["apply_ready"] = False
            data["blockers"] = ["preview validation failed"]
            self._write_json(preflight, data)

            packet = build_command_packet(preflight)

        self.assertFalse(packet["packet_ready"])
        self.assertIn("preflight is not apply_ready", packet["blockers"])
        self.assertIn("preview validation failed", packet["blockers"])

    def test_write_packet_outputs_report_and_json(self):
        try:
            from scripts.render_reviewed_label_apply_command_packet import write_command_packet
        except ModuleNotFoundError:
            self.fail("scripts.render_reviewed_label_apply_command_packet should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            preflight = root / "preflight.json"
            report = root / "packet.md"
            json_report = root / "packet.json"
            self._write_json(preflight, self._ready_preflight())

            packet = write_command_packet(preflight, report, json_report)
            report_text = report.read_text(encoding="utf-8")
            json_report_exists = json_report.exists()

        self.assertTrue(packet["packet_ready"])
        self.assertIn("Manual Confirmation Command Packet", report_text)
        self.assertTrue(json_report_exists)
