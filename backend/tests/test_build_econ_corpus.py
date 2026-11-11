import unittest
from collections import Counter
from datetime import datetime

from backend.scripts.build_econ_corpus import (
    build_records,
    clean_text,
    econ_topics,
    is_noise_title,
    source_doc_id,
)

START, END = datetime(2025, 6, 10), datetime(2026, 6, 10, 23, 59, 59)
# Longer than the 200-char id prefix, so copies that differ later in the body share an evidence id
# (the real duplicate found in the 经济日报 CSV differed at char 236).
BODY = "国家统计局发布数据显示，5月份制造业采购经理指数保持扩张，经济运行稳中有进，新质生产力加快发展。" * 6


def _raw(**overrides):
    row = {"source": "jjrb", "date": "2026/5/26", "section": "要闻", "title": "经济运行稳中有进",
           "content": BODY, "url": "http://paper.ce.cn/x.html"}
    row.update(overrides)
    return row


class CleaningRuleTests(unittest.TestCase):
    def test_rmrb_page_header_and_mojibake_are_removed(self):
        raw = "人民日报2025年06月10日\r\n\t\t\tTue\n新华社北京6月9日电?国务院举行会议。"
        self.assertEqual(clean_text(raw, source="rmrb"), "新华社北京6月9日电国务院举行会议。")

    def test_page_furniture_titles_are_noise(self):
        for title in ("图片新闻", "来稿邮箱", "本版责编：张三 李四", "广告"):
            self.assertTrue(is_noise_title(title), title)
        self.assertFalse(is_noise_title("经济运行稳中有进"))

    def test_byline_alone_does_not_make_article_economic(self):
        self.assertEqual(econ_topics("抗日英雄事迹", "经济日报记者 张三报道：某地举行纪念活动。", "要闻"), [])
        self.assertIn("economy_finance", econ_topics("一季度GDP增长5%", "经济运行稳中有进。", "要闻"))

    def test_evidence_id_is_stable_and_documented(self):
        doc_hash = source_doc_id("jjrb", datetime(2026, 5, 26), "要闻", "标题", "正文")
        self.assertEqual(doc_hash, source_doc_id("jjrb", datetime(2026, 5, 26), "要闻", "标题", "正文"))
        self.assertRegex(doc_hash, r"^[0-9a-f]{16}$")


class BuildRecordsTests(unittest.TestCase):
    def test_window_noise_short_and_non_econ_filters(self):
        stats = Counter()
        rows = [
            _raw(),
            _raw(date="2024/1/1"),
            _raw(title="图片新闻"),
            _raw(title="短讯", content="太短了"),
            _raw(title="抗日英雄事迹", content="某地举行纪念活动，缅怀先烈事迹。" * 6),
        ]
        records = build_records(rows, START, END, stats)
        self.assertEqual([r["title"] for r in records], ["经济运行稳中有进"])
        self.assertEqual((stats["in_window"], stats["noise_dropped"], stats["too_short"], stats["not_econ"]),
                         (4, 1, 1, 1))
        record = records[0]
        self.assertEqual(record["evidence_id"], f"news:jjrb:{record['source_doc_id']}")
        self.assertEqual(record["doc_id"], f"jjrb:{record['source_doc_id']}")
        self.assertEqual(record["publish_time"], "2026-05-26 00:00:00")

    def test_same_article_scraped_twice_keeps_longer_copy(self):
        stats = Counter()
        longer = BODY + "（新增小标题）补充段落内容。"
        records = build_records([_raw(), _raw(content=longer)], START, END, stats)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["content"], longer)
        self.assertEqual(stats["duplicates_removed"], 1)

    def test_same_title_and_opening_on_another_day_is_duplicate(self):
        stats = Counter()
        records = build_records([_raw(), _raw(date="2026/5/27")], START, END, stats)
        self.assertEqual(len(records), 1)


if __name__ == "__main__":
    unittest.main()
