import unittest

from harness.citation_repair import repair_citations

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


if __name__ == "__main__":
    unittest.main()
