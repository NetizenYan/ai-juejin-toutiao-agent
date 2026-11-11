import unittest

from agent.harness.citation_repair import repair_citations

REFS = [
    "news:rmrb:60c32c906a6f8970",
    "news:rmrb:75f7f05fe81653ab",
    "news:rmrb:4ffdebabe1ac8a46",
    "news:jjrb:3de7f2af38dfd107",
    "news:6531",
]


class CitationRepairTests(unittest.TestCase):
    def test_fixes_forms_seen_in_e2e_traces(self):
        cases = {
            "要点［news:rmrb:60c32c906a6f8970］": "要点[news:rmrb:60c32c906a6f8970]",  # full-width brackets
            "要点 [news:60c32c906a6f8970]。": "要点 [news:rmrb:60c32c906a6f8970]。",  # source missing
            "要点 [news:jjrb:4ffdebabe1ac8a46]": "要点 [news:rmrb:4ffdebabe1ac8a46]",  # wrong source
            "要点 [news:rmrb:75f05fe81653ab]": "要点 [news:rmrb:75f7f05fe81653ab]",  # two chars dropped
        }
        for raw, expected in cases.items():
            fixed, repairs = repair_citations(raw, REFS)
            self.assertEqual(fixed, expected, raw)
            self.assertTrue(repairs)

    def test_leaves_valid_and_unresolvable_citations_alone(self):
        text = "对 [news:6531]，没编号 [news:rmrb]，编造 [news:jjrb:ffffffffffffffff]"
        fixed, repairs = repair_citations(text, REFS)
        self.assertEqual(fixed, text)
        self.assertEqual(repairs, [])

    def test_ambiguous_near_match_is_not_guessed(self):
        refs = ["news:rmrb:aaaaaaaaaaaaaaaa", "news:rmrb:aaaaaaaaaaaaaabb"]
        fixed, _ = repair_citations("[news:rmrb:aaaaaaaaaaaaaaab]", refs)
        self.assertEqual(fixed, "[news:rmrb:aaaaaaaaaaaaaaab]")

    def test_a_tag_naming_no_report_is_removed(self):
        for tag in ("[news:无]", "[news:]", "[news: none ]", "[news:N/A]"):
            fixed, repairs = repair_citations(f"上一轮没有生成那张表 {tag}。", REFS)
            self.assertEqual(fixed, "上一轮没有生成那张表。", tag)
            self.assertEqual(repairs[0]["kind"], "empty")

    def test_the_format_placeholder_is_not_left_looking_like_a_citation(self):
        fixed, repairs = repair_citations("新闻事实后面都要保留 [news:ID] 出处标注。", REFS)

        self.assertEqual(fixed, "新闻事实后面都要保留 [news:编号] 出处标注。")
        self.assertEqual(repairs[0]["kind"], "placeholder")
        self.assertEqual(repair_citations("[news:6531]", REFS), ("[news:6531]", []))


if __name__ == "__main__":
    unittest.main()
