import json
import tempfile
import unittest
from pathlib import Path


class RetrievalSplitPreviewTests(unittest.TestCase):
    def _rows(self, case_counts: dict[str, int]) -> list[dict]:
        rows = []
        for case_type, count in case_counts.items():
            prefix = case_type.split("_", 1)[0].lower()
            for idx in range(count):
                rows.append(
                    {
                        "id": f"{prefix}_{idx:03d}",
                        "question": f"{case_type} question {idx}",
                        "expected_route": "econ_finance_query",
                        "gold_evidence_ids": [f"news:jjrb:{prefix}{idx:04d}"],
                        "should_answer": True,
                        "should_refuse": False,
                        "must_have_citations": True,
                        "case_type": case_type,
                        "notes": "test row",
                    }
                )
        return rows

    def _write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
            encoding="utf-8",
        )

    def test_build_split_is_stratified_deterministic_and_non_overlapping(self):
        try:
            from scripts.build_retrieval_split_preview import build_split_preview
        except ModuleNotFoundError:
            self.fail("scripts.build_retrieval_split_preview should exist")

        rows = self._rows({"A_exact_news_qa": 10, "B_context_follow_up": 10})

        first = build_split_preview(rows, heldout_ratio=0.3, min_heldout=0, seed="fixed")
        second = build_split_preview(rows, heldout_ratio=0.3, min_heldout=0, seed="fixed")

        self.assertEqual([row["id"] for row in first.train_rows], [row["id"] for row in second.train_rows])
        self.assertEqual([row["id"] for row in first.heldout_rows], [row["id"] for row in second.heldout_rows])
        self.assertEqual(first.summary["train_count"], 14)
        self.assertEqual(first.summary["heldout_count"], 6)
        self.assertEqual(first.summary["class_counts"]["A_exact_news_qa"]["heldout"], 3)
        self.assertEqual(first.summary["class_counts"]["B_context_follow_up"]["heldout"], 3)

        train_ids = {row["id"] for row in first.train_rows}
        heldout_ids = {row["id"] for row in first.heldout_rows}
        self.assertEqual(train_ids & heldout_ids, set())
        self.assertEqual(len(train_ids | heldout_ids), len(rows))
        self.assertTrue(first.summary["preview_only"])

    def test_heldout_target_uses_ratio_and_minimum_for_large_gold_preview(self):
        try:
            from scripts.build_retrieval_split_preview import build_split_preview
        except ModuleNotFoundError:
            self.fail("scripts.build_retrieval_split_preview should exist")

        rows = self._rows(
            {
                "A_exact_news_qa": 20,
                "B_context_follow_up": 20,
                "C_time_sensitive": 15,
                "D_source_limited": 15,
                "E_multi_document": 15,
                "F_similar_distractor": 10,
                "G_no_answer": 10,
                "H_investment_boundary": 10,
            }
        )

        split = build_split_preview(rows, heldout_ratio=0.3, min_heldout=30, seed="20260622")

        self.assertEqual(split.summary["input_count"], 115)
        self.assertEqual(split.summary["heldout_count"], 35)
        self.assertEqual(split.summary["train_count"], 80)
        self.assertGreaterEqual(split.summary["class_counts"]["A_exact_news_qa"]["heldout"], 5)
        self.assertGreaterEqual(split.summary["class_counts"]["H_investment_boundary"]["heldout"], 3)

    def test_duplicate_gold_ids_raise_value_error(self):
        try:
            from scripts.build_retrieval_split_preview import build_split_preview
        except ModuleNotFoundError:
            self.fail("scripts.build_retrieval_split_preview should exist")

        rows = self._rows({"A_exact_news_qa": 2})
        rows[1]["id"] = rows[0]["id"]

        with self.assertRaisesRegex(ValueError, "duplicate gold id"):
            build_split_preview(rows, heldout_ratio=0.3, min_heldout=0, seed="fixed")

    def test_shared_evidence_rows_stay_in_same_preview_split(self):
        try:
            from scripts.build_retrieval_split_preview import build_split_preview
        except ModuleNotFoundError:
            self.fail("scripts.build_retrieval_split_preview should exist")

        rows = [
            {
                "id": "exact_shared",
                "question": "shared exact question",
                "expected_route": "econ_finance_query",
                "gold_evidence_ids": ["news:jjrb:shared0000000001"],
                "should_answer": True,
                "should_refuse": False,
                "must_have_citations": True,
                "case_type": "A_exact_news_qa",
                "notes": "test row",
            },
            {
                "id": "context_shared",
                "turns": ["shared context", "follow up"],
                "expected_route": "econ_finance_query",
                "gold_evidence_ids": ["news:jjrb:shared0000000001"],
                "should_answer": True,
                "should_refuse": False,
                "must_have_citations": True,
                "case_type": "B_context_follow_up",
                "notes": "test row",
            },
            *self._rows({"C_time_sensitive": 6, "D_source_limited": 6}),
        ]

        split = build_split_preview(rows, heldout_ratio=0.5, min_heldout=0, seed="fixed")
        train_ids = {row["id"] for row in split.train_rows}
        heldout_ids = {row["id"] for row in split.heldout_rows}

        self.assertEqual("exact_shared" in train_ids, "context_shared" in train_ids)
        self.assertEqual("exact_shared" in heldout_ids, "context_shared" in heldout_ids)
        self.assertEqual(split.summary["evidence_group_overlap_count"], 0)
        self.assertGreaterEqual(split.summary["evidence_group_count"], 1)

    def test_grouped_split_keeps_heldout_near_target_when_groups_cross_classes(self):
        try:
            from scripts.build_retrieval_split_preview import build_split_preview
        except ModuleNotFoundError:
            self.fail("scripts.build_retrieval_split_preview should exist")

        shared_rows = []
        for idx, case_type in enumerate(
            ["A_exact_news_qa", "B_context_follow_up", "C_time_sensitive", "D_source_limited"]
        ):
            shared_rows.append(
                {
                    "id": f"shared_{idx}",
                    "question": f"shared {idx}",
                    "expected_route": "econ_finance_query",
                    "gold_evidence_ids": ["news:jjrb:shared-cross-class"],
                    "should_answer": True,
                    "should_refuse": False,
                    "must_have_citations": True,
                    "case_type": case_type,
                    "notes": "test row",
                }
            )
        rows = [*shared_rows, *self._rows({"E_multi_document": 10, "F_similar_distractor": 10})]

        split = build_split_preview(rows, heldout_ratio=0.25, min_heldout=0, seed="fixed")

        self.assertLessEqual(split.summary["heldout_count"], 7)
        self.assertGreaterEqual(split.summary["heldout_count"], 5)
        self.assertEqual(split.summary["evidence_group_overlap_count"], 0)

    def test_write_split_preview_outputs_jsonl_summary_and_report(self):
        try:
            from scripts.build_retrieval_split_preview import write_split_preview
        except ModuleNotFoundError:
            self.fail("scripts.build_retrieval_split_preview should exist")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            gold = root / "gold.jsonl"
            train = root / "preview" / "train.jsonl"
            heldout = root / "preview" / "heldout.jsonl"
            summary = root / "preview" / "summary.json"
            report = root / "preview" / "report.md"
            self._write_jsonl(gold, self._rows({"A_exact_news_qa": 10, "B_context_follow_up": 10}))

            result = write_split_preview(
                gold,
                train,
                heldout,
                summary,
                report,
                heldout_ratio=0.3,
                min_heldout=0,
                seed="fixed",
            )

            self.assertEqual(result["input_count"], 20)
            self.assertEqual(result["heldout_count"], 6)
            self.assertTrue(train.exists())
            self.assertTrue(heldout.exists())
            self.assertTrue(summary.exists())
            self.assertTrue(report.exists())
            self.assertIn("preview", result["train_path"])
            report_text = report.read_text(encoding="utf-8")
            self.assertIn("Preview Only", report_text)
            self.assertIn("Evidence group overlap", report_text)
