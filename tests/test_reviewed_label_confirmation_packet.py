import json
import tempfile
import unittest
from pathlib import Path


class ReviewedLabelConfirmationPacketTests(unittest.TestCase):
    def _write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
            encoding="utf-8",
        )

    def test_build_packet_counts_decisions_and_case_types(self):
        try:
            from scripts.render_reviewed_label_confirmation_packet import build_confirmation_packet
        except ModuleNotFoundError:
            self.fail("scripts.render_reviewed_label_confirmation_packet should exist")

        candidates = [
            {"id": "candidate_a1", "case_type": "A_exact_news_qa", "query_or_turns": ["A?"]},
            {"id": "candidate_b1", "case_type": "B_context_follow_up", "query_or_turns": ["B1", "B2"]},
        ]
        labels = [
            {
                "candidate_id": "candidate_a1",
                "decision": "accept_as_gold",
                "gold_id": "a1_reviewed",
                "question": "A?",
                "turns": None,
                "case_type": "A_exact_news_qa",
                "gold_evidence_ids": ["news:jjrb:a1"],
                "notes": "Verify manually.",
            },
            {
                "candidate_id": "candidate_b1",
                "decision": "merge_with_existing",
                "existing_gold_id": "b1",
                "case_type": "B_context_follow_up",
                "notes": "Duplicate.",
            },
        ]

        packet = build_confirmation_packet(candidates, labels)

        self.assertEqual(packet["summary"]["label_count"], 2)
        self.assertEqual(packet["summary"]["decision_counts"]["accept_as_gold"], 1)
        self.assertEqual(packet["summary"]["decision_counts"]["merge_with_existing"], 1)
        self.assertEqual(packet["summary"]["case_type_decision_counts"]["A_exact_news_qa"]["accept_as_gold"], 1)
        self.assertEqual(packet["summary"]["case_type_decision_counts"]["B_context_follow_up"]["merge_with_existing"], 1)
        self.assertEqual(packet["rows"][0]["evidence_count"], 1)
        self.assertEqual(packet["rows"][1]["target_gold_id"], "b1")

    def test_render_markdown_includes_confirmation_columns_and_guardrails(self):
        try:
            from scripts.render_reviewed_label_confirmation_packet import (
                build_confirmation_packet,
                render_markdown,
            )
        except ModuleNotFoundError:
            self.fail("scripts.render_reviewed_label_confirmation_packet should exist")

        packet = build_confirmation_packet(
            [{"id": "candidate_a1", "case_type": "A_exact_news_qa", "query_or_turns": ["A?"]}],
            [
                {
                    "candidate_id": "candidate_a1",
                    "decision": "accept_as_gold",
                    "gold_id": "a1_reviewed",
                    "question": "A?",
                    "turns": None,
                    "case_type": "A_exact_news_qa",
                    "gold_evidence_ids": ["news:jjrb:a1"],
                    "notes": "Verify manually.",
                }
            ],
        )

        markdown = render_markdown(packet)

        self.assertIn("Reviewed Label Confirmation Packet", markdown)
        self.assertIn("Reviewer confirmation", markdown)
        self.assertIn("candidate_a1", markdown)
        self.assertIn("Do not copy this packet into the official reviewed-label file", markdown)

    def test_write_packet_outputs_markdown_and_json(self):
        try:
            from scripts.render_reviewed_label_confirmation_packet import write_confirmation_packet
        except ModuleNotFoundError:
            self.fail("scripts.render_reviewed_label_confirmation_packet should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            candidates_path = root / "candidates.jsonl"
            labels_path = root / "labels.jsonl"
            report_path = root / "packet.md"
            json_path = root / "packet.json"
            self._write_jsonl(
                candidates_path,
                [{"id": "candidate_a1", "case_type": "A_exact_news_qa", "query_or_turns": ["A?"]}],
            )
            self._write_jsonl(
                labels_path,
                [
                    {
                        "candidate_id": "candidate_a1",
                        "decision": "accept_as_gold",
                        "gold_id": "a1_reviewed",
                        "question": "A?",
                        "turns": None,
                        "case_type": "A_exact_news_qa",
                        "gold_evidence_ids": ["news:jjrb:a1"],
                        "notes": "Verify manually.",
                    }
                ],
            )

            packet = write_confirmation_packet(candidates_path, labels_path, report_path, json_path)

            self.assertEqual(packet["summary"]["label_count"], 1)
            self.assertTrue(report_path.exists())
            self.assertTrue(json_path.exists())
            data = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(data["summary"]["decision_counts"]["accept_as_gold"], 1)
