import unittest


class GoldExpansionCoverageTests(unittest.TestCase):
    def test_summarize_coverage_counts_formal_candidate_and_deficits(self):
        try:
            from scripts.report_gold_expansion_coverage import summarize_coverage
        except ModuleNotFoundError:
            self.fail("scripts.report_gold_expansion_coverage should exist")

        gold_rows = [
            {"id": "a1", "case_type": "A_exact_news_qa"},
            {"id": "b1", "case_type": "B_context_follow_up"},
            {"id": "h1", "case_type": "H_investment_boundary"},
        ]
        candidate_rows = [
            {"id": "candidate_a2", "case_type": "A_exact_news_qa"},
            {"id": "candidate_b2", "case_type": "B_context_follow_up"},
        ]

        summary = summarize_coverage(
            gold_rows,
            candidate_rows,
            targets={
                "A_exact_news_qa": 3,
                "B_context_follow_up": 3,
                "H_investment_boundary": 2,
            },
            target_total=6,
        )

        self.assertEqual(summary.formal_count, 3)
        self.assertEqual(summary.candidate_count, 2)
        self.assertEqual(summary.total_deficit_formal_only, 3)
        self.assertEqual(summary.total_deficit_if_all_candidates_accepted, 1)
        self.assertEqual(summary.formal_counts["A_exact_news_qa"], 1)
        self.assertEqual(summary.candidate_counts["A_exact_news_qa"], 1)
        self.assertEqual(summary.deficits_formal_only["A_exact_news_qa"], 2)
        self.assertEqual(summary.deficits_if_all_candidates_accepted["A_exact_news_qa"], 1)
        self.assertEqual(summary.deficits_if_all_candidates_accepted["H_investment_boundary"], 1)
        self.assertEqual(summary.candidate_gaps, ["H_investment_boundary"])

    def test_render_markdown_includes_actionable_gaps(self):
        try:
            from scripts.report_gold_expansion_coverage import render_markdown, summarize_coverage
        except ModuleNotFoundError:
            self.fail("scripts.report_gold_expansion_coverage should exist")

        summary = summarize_coverage(
            [{"id": "h1", "case_type": "H_investment_boundary"}],
            [],
            targets={"H_investment_boundary": 2},
            target_total=3,
        )

        markdown = render_markdown(summary)

        self.assertIn("# 3.3 Gold Expansion Coverage", markdown)
        self.assertIn("Formal gold count: 1", markdown)
        self.assertIn("Candidate count: 0", markdown)
        self.assertIn("H_investment_boundary", markdown)
        self.assertIn("Need 2 more reviewed/accepted cases to reach 3 total.", markdown)
