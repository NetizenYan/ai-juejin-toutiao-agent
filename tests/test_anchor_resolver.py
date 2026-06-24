import unittest

from harness.anchor_resolver import (
    confirmed_anchor_from_user_selection,
    extract_anchor_candidates_from_confirmation,
    looks_like_anchor_query,
    render_anchor_confirmation,
    resolve_anchor_candidates,
)


class AnchorResolverTests(unittest.TestCase):
    def test_detects_fuzzy_news_memory_query(self):
        self.assertTrue(looks_like_anchor_query("我记得2024年5月经济日报发过一篇关于新质生产力的新闻"))
        self.assertFalse(looks_like_anchor_query("你好，介绍一下你自己"))

    def test_station_internal_medium_or_high_candidates_require_confirmation(self):
        items = [
            {
                "id": "jjrb:001",
                "evidence_id": "news:jjrb:001",
                "title": "因地制宜发展新质生产力",
                "summary": "经济日报报道新质生产力。",
                "source": "经济日报",
                "publish_time": "2024-05-12",
            }
        ]

        resolution = resolve_anchor_candidates("我记得2024年5月经济日报关于新质生产力的新闻", items)

        self.assertEqual(resolution.state, "WAITING_USER_CONFIRMATION")
        self.assertEqual(resolution.candidates[0].match_confidence, "high")
        self.assertEqual(resolution.candidates[0].source_credibility, "high")
        self.assertTrue(resolution.requires_user_confirmation)

    def test_low_confidence_items_become_leads_not_candidates(self):
        items = [
            {
                "id": "misc:001",
                "evidence_id": "news:misc:001",
                "title": "完全无关的体育新闻",
                "summary": "体育内容。",
                "source": "未知来源",
            }
        ]

        resolution = resolve_anchor_candidates("我记得经济日报关于新质生产力的新闻", items)

        self.assertEqual(resolution.candidates, [])
        self.assertEqual(len(resolution.leads), 1)
        self.assertEqual(resolution.state, "NEEDS_EXTERNAL_RESEARCH")

    def test_confirmation_render_includes_evidence_id_and_not_direct_answer(self):
        resolution = resolve_anchor_candidates(
            "我记得经济日报关于新质生产力的新闻",
            [{
                "id": "jjrb:001",
                "evidence_id": "news:jjrb:001",
                "title": "因地制宜发展新质生产力",
                "summary": "经济日报报道新质生产力。",
                "source": "经济日报",
                "publish_time": "2024-05-12",
            }],
        )

        text = render_anchor_confirmation(resolution)

        self.assertIn("请确认", text)
        self.assertIn("news:jjrb:001", text)
        self.assertIn("因地制宜发展新质生产力", text)
        self.assertNotIn("政策走向是", text)

    def test_user_selection_confirms_match_but_preserves_low_source_credibility(self):
        resolution = resolve_anchor_candidates(
            "我记得X上有一条关于新质生产力的新闻",
            [{
                "id": "x:001",
                "evidence_id": "https://x.example/post/1",
                "title": "网传新质生产力相关消息",
                "summary": "社媒线索。",
                "source": "X",
                "acquisition_method": "web",
            }],
        )

        confirmed = resolution.candidates[0].as_confirmed_metadata()

        self.assertEqual(confirmed["match_confidence"], "confirmed")
        self.assertEqual(confirmed["source_credibility"], "low")

    def test_review_safe_policy_keeps_low_credibility_external_item_as_lead(self):
        items = [{
            "id": "x:001",
            "evidence_id": "https://x.example/post/1",
            "title": "网传新质生产力相关消息",
            "summary": "社媒线索。",
            "source": "X",
            "acquisition_method": "web",
        }]

        local = resolve_anchor_candidates("我记得X上有一条关于新质生产力的新闻", items, source_policy="local_test")
        review_safe = resolve_anchor_candidates("我记得X上有一条关于新质生产力的新闻", items, source_policy="review_safe")

        self.assertEqual(len(local.candidates), 1)
        self.assertEqual(local.candidates[0].source_credibility, "low")
        self.assertEqual(review_safe.candidates, [])
        self.assertEqual(len(review_safe.leads), 1)

    def test_ocr_screenshot_topic_match_becomes_confirmable_low_credibility_candidate(self):
        items = [{
            "id": "news:7420",
            "evidence_id": "news:7420",
            "title": "外网页面截图 OCR 测试",
            "summary": "新质生产力政策信号持续释放，高质量发展、科技创新和产业升级成为关键词。",
            "source": "X",
            "acquisition_method": "ocr_screenshot",
            "source_credibility": "low",
            "verification_status": "unverified",
        }]

        resolution = resolve_anchor_candidates(
            "我记得外网截图里有一条关于新质生产力政策信号的新闻",
            items,
        )
        text = render_anchor_confirmation(resolution)

        self.assertEqual(resolution.state, "WAITING_USER_CONFIRMATION")
        self.assertEqual(len(resolution.candidates), 1)
        self.assertEqual(resolution.candidates[0].match_confidence, "medium")
        self.assertEqual(resolution.candidates[0].source_credibility, "low")
        self.assertEqual(resolution.candidates[0].acquisition_method, "ocr_screenshot")
        self.assertTrue(resolution.requires_user_confirmation)
        self.assertIn("可信度提示", text)
        self.assertIn("X", text)

    def test_station_matched_ocr_candidate_render_includes_cross_check_and_warning(self):
        items = [{
            "id": "ocr:x:001",
            "evidence_id": "https://x.example/post/1",
            "title": "External OCR policy signal",
            "summary": "Policy signal from an OCR screenshot.",
            "source": "X",
            "acquisition_method": "ocr_screenshot",
            "source_credibility": "low",
            "verification_status": "station_matched",
            "external_verification": {
                "verification_status": "station_matched",
                "matched_station_evidence_ids": ["news:station:1"],
                "matched_station_titles": ["Station matched policy signal"],
                "user_warning": "external OCR lead has station match but low source credibility",
            },
        }]

        resolution = resolve_anchor_candidates("OCR X screenshot policy signal", items)
        text = render_anchor_confirmation(resolution)

        self.assertEqual(resolution.state, "WAITING_USER_CONFIRMATION")
        self.assertIn("news:station:1", text)
        self.assertIn("Station matched policy signal", text)
        self.assertIn("external OCR lead has station match but low source credibility", text)
        self.assertNotIn("not cross-checked", text)

    def test_confirmation_parser_preserves_station_match_metadata(self):
        resolution = resolve_anchor_candidates(
            "OCR X screenshot policy signal",
            [{
                "id": "ocr:x:001",
                "evidence_id": "https://x.example/post/1",
                "title": "External OCR policy signal",
                "summary": "Policy signal from an OCR screenshot.",
                "source": "X",
                "acquisition_method": "ocr_screenshot",
                "source_credibility": "low",
                "verification_status": "station_matched",
                "external_verification": {
                    "verification_status": "station_matched",
                    "matched_station_evidence_ids": ["news:station:1"],
                    "matched_station_titles": ["Station matched policy signal"],
                    "user_warning": "external OCR lead has station match but low source credibility",
                },
            }],
        )

        parsed = extract_anchor_candidates_from_confirmation(render_anchor_confirmation(resolution))

        self.assertEqual(parsed[0].verification_status, "station_matched")
        self.assertEqual(
            parsed[0].external_verification["matched_station_evidence_ids"],
            ["news:station:1"],
        )
        self.assertIn("low source credibility", parsed[0].external_verification["user_warning"])

    def test_user_selection_from_confirmation_text_picks_numbered_candidate(self):
        resolution = resolve_anchor_candidates(
            "我记得经济日报关于新质生产力的新闻",
            [
                {
                    "id": "jjrb:first",
                    "evidence_id": "news:jjrb:first",
                    "title": "第一篇新质生产力报道",
                    "summary": "经济日报报道新质生产力。",
                    "source": "经济日报",
                    "publish_time": "2026-05-01",
                },
                {
                    "id": "jjrb:second",
                    "evidence_id": "news:jjrb:second",
                    "title": "第二篇新质生产力报道",
                    "summary": "经济日报报道新质生产力。",
                    "source": "经济日报",
                    "publish_time": "2026-05-02",
                },
            ],
        )

        parsed = extract_anchor_candidates_from_confirmation(render_anchor_confirmation(resolution))
        confirmed = confirmed_anchor_from_user_selection("就是第一篇，请按这篇解释", parsed)

        self.assertIsNotNone(confirmed)
        self.assertEqual(confirmed["anchor_id"], "news:jjrb:first")
        self.assertEqual(confirmed["match_confidence"], "confirmed")
        self.assertEqual(confirmed["source_credibility"], "high")

    def test_medium_external_candidate_render_includes_credibility_hint(self):
        resolution = resolve_anchor_candidates(
            "我记得Reuters在2024年5月有一篇关于新质生产力政策表述的报道",
            [{
                "id": "https://www.reuters.com/world/china/policy-new-productive-forces-2024-05-12/",
                "url": "https://www.reuters.com/world/china/policy-new-productive-forces-2024-05-12/",
                "title": "Reuters: China policy mentions new productive forces",
                "summary": "Reuters reported a policy discussion about 新质生产力 in May 2024.",
                "source": "Reuters",
                "source_credibility": "medium",
                "verification_status": "unverified",
                "acquisition_method": "web_search",
                "published_at": "2024-05-12",
            }],
        )

        text = render_anchor_confirmation(resolution)

        self.assertIn("Reuters", text)
        self.assertIn("可信度提示", text)
        self.assertIn("尚未被站内或主流来源交叉验证", text)


if __name__ == "__main__":
    unittest.main()
