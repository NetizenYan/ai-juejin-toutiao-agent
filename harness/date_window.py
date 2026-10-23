"""Explicit publication-date windows in user questions ("2026年5月", "2026年6月上旬", "2026年3月5日").

Retrieval used to ignore these, so "2026年5月经济日报发过一篇…" ranked articles from any month and
"2026年3月…有没有报道" answered from other months instead of refusing. The window becomes a hard
publish_ts range filter.

Only windows with an explicit year and month are used. A bare year is skipped on purpose: in
"到2030年服务业总规模迈上100万亿元台阶" the year is the subject, not the publication date.
publish_ts values are dates encoded as UTC midnight (newspapers) or naive local broadcast times,
so windows are computed on UTC calendar days.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import datetime, timezone

_YM = r"(20\d{2})\s*年\s*(\d{1,2})\s*月"
DAY_RE = re.compile(_YM + r"\s*(\d{1,2})\s*[日号]")
RANGE_RE = re.compile(_YM + r"\s*(?:到|至|—|-|~)\s*(?:(20\d{2})\s*年\s*)?(\d{1,2})\s*月")
# A bare "中" is left out: "2026年5月中国…" is not mid-May.
PART_RE = re.compile(_YM + r"\s*(上旬|中旬|下旬|初|底|末)")
MONTH_RE = re.compile(_YM)
PART_DAYS = {"上旬": (1, 10), "初": (1, 10), "中旬": (11, 20), "下旬": (21, 31), "底": (21, 31), "末": (21, 31)}


@dataclass(frozen=True)
class DateWindow:
    start_ts: int  # inclusive
    end_ts: int  # exclusive
    label: str

    def to_dict(self) -> dict:
        return {"start_ts": self.start_ts, "end_ts": self.end_ts, "label": self.label}


def _ts(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp())


def _month_end_exclusive(year: int, month: int) -> int:
    return _ts(year + 1, 1, 1) if month == 12 else _ts(year, month + 1, 1)


def _valid(year: int, month: int, day: int = 1) -> bool:
    return 1 <= month <= 12 and 1 <= day <= calendar.monthrange(year, month)[1]


def explicit_date_window(query: str) -> DateWindow | None:
    text = query or ""
    if match := DAY_RE.search(text):
        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if _valid(year, month, day):
            start = _ts(year, month, day)
            # Coverage of a dated event usually runs in the next day's paper.
            return DateWindow(start, start + 2 * 86400, f"{year}-{month:02d}-{day:02d}+1d")
    if match := RANGE_RE.search(text):
        year, month = int(match.group(1)), int(match.group(2))
        end_year = int(match.group(3) or year)
        end_month = int(match.group(4))
        if _valid(year, month) and _valid(end_year, end_month) and (end_year, end_month) >= (year, month):
            return DateWindow(_ts(year, month, 1), _month_end_exclusive(end_year, end_month),
                              f"{year}-{month:02d}..{end_year}-{end_month:02d}")
    if match := PART_RE.search(text):
        year, month = int(match.group(1)), int(match.group(2))
        if _valid(year, month):
            first, last = PART_DAYS[match.group(3)]
            last = min(last, calendar.monthrange(year, month)[1])
            return DateWindow(_ts(year, month, first), _ts(year, month, last) + 86400,
                              f"{year}-{month:02d}-{first:02d}..{last:02d}")
    if match := MONTH_RE.search(text):
        year, month = int(match.group(1)), int(match.group(2))
        if _valid(year, month):
            return DateWindow(_ts(year, month, 1), _month_end_exclusive(year, month), f"{year}-{month:02d}")
    return None
