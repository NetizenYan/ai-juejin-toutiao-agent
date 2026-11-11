import unittest
from datetime import datetime, timezone

from agent.harness.date_window import explicit_date_window


def _days(window):
    to_date = lambda ts: datetime.fromtimestamp(ts, timezone.utc).date().isoformat()
    return to_date(window.start_ts), to_date(window.end_ts)


class DateWindowTests(unittest.TestCase):
    def test_month_and_parts_of_month(self):
        self.assertEqual(_days(explicit_date_window("我记得2026年5月经济日报发过一篇")), ("2026-05-01", "2026-06-01"))
        self.assertEqual(_days(explicit_date_window("2026年6月初金融支持三农")), ("2026-06-01", "2026-06-11"))
        self.assertEqual(_days(explicit_date_window("2026年5月中旬智能经济")), ("2026-05-11", "2026-05-21"))
        self.assertEqual(_days(explicit_date_window("2026年2月底的报道")), ("2026-02-21", "2026-03-01"))
        self.assertEqual(_days(explicit_date_window("2025年12月的报道")), ("2025-12-01", "2026-01-01"))

    def test_day_window_includes_next_day_paper(self):
        self.assertEqual(_days(explicit_date_window("2026年3月5日开幕的两会")), ("2026-03-05", "2026-03-07"))

    def test_month_ranges(self):
        self.assertEqual(_days(explicit_date_window("2025年12月至2026年2月")), ("2025-12-01", "2026-03-01"))
        self.assertEqual(_days(explicit_date_window("2026年3月到5月")), ("2026-03-01", "2026-06-01"))

    def test_no_window_for_bare_years_names_or_bad_dates(self):
        for query in ("到2030年服务业总规模迈上100万亿元台阶", "蓝鲸计划2029", "2026年13月", "最近有什么新闻"):
            self.assertIsNone(explicit_date_window(query), query)
        # "5月中国…" is the whole month, not mid-May.
        self.assertEqual(_days(explicit_date_window("2026年5月中国经济")), ("2026-05-01", "2026-06-01"))


if __name__ == "__main__":
    unittest.main()
