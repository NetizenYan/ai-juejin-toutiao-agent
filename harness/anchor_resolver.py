"""News anchor resolution for fuzzy B-class follow-up workflows.

This module is deliberately deterministic. It proposes candidate news anchors
and search leads; it does not decide facts for the user.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


ANCHOR_QUERY_MARKERS = (
    "我记得",
    "好像",
    "是不是有一篇",
    "发过一篇",
    "发布了一篇",
    "这篇报道",
    "那篇报道",
    "这条新闻",
)
SOURCE_TERMS = (
    "经济日报",
    "人民日报",
    "新闻联播",
    "新华社",
    "Reuters",
    "路透",
    "X",
    "Instagram",
    "Ins",
)
TOPIC_TERMS = (
    "新质生产力",
    "高质量发展",
    "制造业",
    "房地产",
    "A股",
    "科技创新",
    "产业升级",
)
OCR_QUERY_MARKERS = ("OCR", "ocr", "截图", "截屏", "图片", "页面截图", "外网截图")
LOW_CREDIBILITY_SOURCES = {"x", "instagram", "ins", "未知来源", "unknown"}
HIGH_CREDIBILITY_SOURCES = {"经济日报", "人民日报", "新闻联播", "新华社"}
YEAR_MONTH_RE = re.compile(r"(20[12]\d)\s*年\s*(\d{1,2})\s*月")
YEAR_RE = re.compile(r"(20[12]\d)\s*年")
CONFIRMATION_ITEM_RE = re.compile(r"^\s*(\d+)\.\s*(.*?)\s*\|\s*(.*?)\s*\|\s*《(.*?)》\s*$")
CONFIRMATION_LINK_RE = re.compile(r"^\s*链接：\s*(\S+)\s*$")
CONFIRMATION_STATION_RE = re.compile(r"^\s*站内对照：\s*(.+?)\s*$")
CONFIRMATION_WARNING_RE = re.compile(r"^\s*风险提示：\s*(.+?)\s*$")
SELECTION_RE = re.compile(r"(?:第\s*)?([1-9一二三四五六七八九])\s*(?:篇|个|条|则|项)")
CHINESE_ORDINALS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


@dataclass(frozen=True)
class AnchorCandidate:
    anchor_id: str
    title: str
    source_name: str
    source_url_or_evidence_id: str
    published_at: str = ""
    snippet: str = ""
    match_confidence: str = "low"
    source_credibility: str = "unknown"
    verification_status: str = "unknown"
    acquisition_method: str = "rag"
    match_reasons: list[str] = field(default_factory=list)
    external_verification: dict[str, Any] = field(default_factory=dict)

    def as_confirmed_metadata(self) -> dict[str, Any]:
        metadata = {
            "anchor_id": self.anchor_id,
            "title": self.title,
            "source_name": self.source_name,
            "source_url": self.source_url_or_evidence_id,
            "match_confidence": "confirmed",
            "source_credibility": self.source_credibility,
            "verification_status": self.verification_status,
            "acquisition_method": self.acquisition_method,
        }
        if self.external_verification:
            metadata["external_verification"] = dict(self.external_verification)
        return metadata


@dataclass(frozen=True)
class AnchorResolution:
    state: str
    query: str
    candidates: list[AnchorCandidate]
    leads: list[AnchorCandidate]
    requires_user_confirmation: bool


def looks_like_anchor_query(query: str) -> bool:
    text = query or ""
    if any(marker in text for marker in ANCHOR_QUERY_MARKERS):
        return True
    return bool(
        ("新闻" in text or "报道" in text or "文章" in text)
        and any(source in text for source in SOURCE_TERMS)
    )


def _extract_query_terms(query: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if term and term in (query or "")]


def _extract_year_month(query: str) -> str:
    match = YEAR_MONTH_RE.search(query or "")
    if not match:
        return ""
    return f"{match.group(1)}-{int(match.group(2)):02d}"


def _extract_year(query: str) -> str:
    match = YEAR_RE.search(query or "")
    return match.group(1) if match else ""


def _item_text(item: dict[str, Any]) -> str:
    return "\n".join(
        str(item.get(key) or "")
        for key in ("title", "summary", "snippet", "text", "chunk_text", "source")
    )


def _source_credibility(source_name: str, evidence_ref: str) -> tuple[str, str]:
    lowered = (source_name or "").strip().lower()
    if evidence_ref.startswith("news:") or source_name in HIGH_CREDIBILITY_SOURCES:
        return "high", "station_internal"
    if lowered in LOW_CREDIBILITY_SOURCES:
        return "low", "unverified"
    return "unknown", "unverified"


def _candidate_from_item(
    query: str,
    item: dict[str, Any],
    *,
    source_policy: str,
) -> AnchorCandidate:
    text = _item_text(item)
    title = str(item.get("title") or "")
    source_name = str(item.get("source") or "")
    evidence_ref = str(item.get("evidence_id") or item.get("source_url") or item.get("url") or item.get("id") or "")
    published_at = str(item.get("publish_time") or item.get("published_at") or "")
    snippet = str(item.get("summary") or item.get("snippet") or item.get("text") or "")
    acquisition_method = str(item.get("acquisition_method") or ("rag" if evidence_ref.startswith("news:") else "web"))
    external_verification = item.get("external_verification")
    if not isinstance(external_verification, dict):
        external_verification = {}

    score = 0
    reasons: list[str] = []
    for source in _extract_query_terms(query, SOURCE_TERMS):
        aliases = (source,)
        if source == "路透":
            aliases = ("路透", "Reuters")
        if any(alias in source_name or alias in text for alias in aliases):
            score += 2
            reasons.append("source_match")
            break
    for topic in _extract_query_terms(query, TOPIC_TERMS):
        if topic in title:
            score += 2
            reasons.append("topic_in_title")
            break
        if topic in text:
            score += 1
            reasons.append("topic_match")
            break
    if acquisition_method == "ocr_screenshot" and any(marker in (query or "") for marker in OCR_QUERY_MARKERS):
        score += 2
        reasons.append("ocr_screenshot_match")
    year_month = _extract_year_month(query)
    if year_month and published_at.startswith(year_month):
        score += 2
        reasons.append("month_match")
    elif _extract_year(query) and published_at.startswith(_extract_year(query)):
        score += 1
        reasons.append("year_match")
    if title and title in query:
        score += 2
        reasons.append("title_exact")
    if external_verification.get("verification_status") == "station_matched":
        score += 1
        reasons.append("station_matched")

    if score >= 5:
        match_confidence = "high"
    elif score >= 3:
        match_confidence = "medium"
    else:
        match_confidence = "low"

    credibility = str(item.get("source_credibility") or "").strip().lower()
    verification = str(item.get("verification_status") or "").strip().lower()
    if not credibility or not verification:
        inferred_credibility, inferred_verification = _source_credibility(source_name, evidence_ref)
        credibility = credibility or inferred_credibility
        verification = verification or inferred_verification
    return AnchorCandidate(
        anchor_id=evidence_ref,
        title=title,
        source_name=source_name,
        source_url_or_evidence_id=evidence_ref,
        published_at=published_at,
        snippet=snippet,
        match_confidence=match_confidence,
        source_credibility=credibility,
        verification_status=verification,
        acquisition_method=acquisition_method,
        match_reasons=reasons or ["weak_match"],
        external_verification=external_verification,
    )


def _source_policy_allows_candidate(candidate: AnchorCandidate, source_policy: str) -> bool:
    policy = (source_policy or "local_test").strip().lower()
    if policy == "local_test":
        return True
    if policy == "strict":
        return candidate.source_credibility == "high" and candidate.verification_status == "station_internal"
    if policy == "review_safe":
        return candidate.source_credibility == "high"
    return True


def resolve_anchor_candidates(
    query: str,
    items: list[dict[str, Any]],
    *,
    source_policy: str = "local_test",
) -> AnchorResolution:
    candidates: list[AnchorCandidate] = []
    leads: list[AnchorCandidate] = []
    for item in items or []:
        candidate = _candidate_from_item(query, item, source_policy=source_policy)
        if candidate.match_confidence in {"high", "medium"} and _source_policy_allows_candidate(candidate, source_policy):
            candidates.append(candidate)
        else:
            leads.append(candidate)

    candidates.sort(
        key=lambda item: (
            2 if item.match_confidence == "high" else 1,
            1 if item.source_credibility == "high" else 0,
            len(item.match_reasons),
        ),
        reverse=True,
    )
    if candidates:
        state = "WAITING_USER_CONFIRMATION"
    elif leads:
        state = "NEEDS_EXTERNAL_RESEARCH"
    else:
        state = "INSUFFICIENT_EVIDENCE"
    return AnchorResolution(
        state=state,
        query=query,
        candidates=candidates[:5],
        leads=leads[:8],
        requires_user_confirmation=bool(candidates),
    )


def render_anchor_confirmation(resolution: AnchorResolution) -> str:
    if not resolution.candidates:
        return (
            "我还不能在站内确认你说的是哪篇新闻。"
            "目前没有中高置信度的站内候选；下一步需要进入站外工具/skills 查证，"
            "或请你补充更具体的发布时间、来源、标题片段或主题关键词。"
            "在确认前我不会把低置信线索当作事实来分析。"
        )

    lines = ["我找到几篇可能是你说的报道，请确认是哪一篇：", ""]
    for index, candidate in enumerate(resolution.candidates[:5], 1):
        label = "最可能" if index == 1 else "其他可能"
        lines.append(f"{label}：")
        lines.append(
            f"{index}. {candidate.published_at or '时间未知'} | "
            f"{candidate.source_name or '来源未知'} | 《{candidate.title or '标题未知'}》"
        )
        lines.append(f"   匹配原因：{', '.join(candidate.match_reasons)}。")
        lines.append(f"   链接：{candidate.source_url_or_evidence_id}")
        external_verification = candidate.external_verification or {}
        station_ids = list(external_verification.get("matched_station_evidence_ids") or [])
        station_titles = list(external_verification.get("matched_station_titles") or [])
        if station_ids or station_titles:
            station_pairs = []
            max_items = max(len(station_ids), len(station_titles))
            for pair_index in range(max_items):
                station_id = str(station_ids[pair_index]) if pair_index < len(station_ids) else ""
                station_title = str(station_titles[pair_index]) if pair_index < len(station_titles) else ""
                station_pairs.append(" | ".join(part for part in (station_id, station_title) if part))
            lines.append(f"   站内对照：{'; '.join(station_pairs)}")
        user_warning = str(external_verification.get("user_warning") or "").strip()
        if user_warning:
            lines.append(f"   风险提示：{user_warning}")
        elif external_verification.get("verification_status") == "station_matched":
            lines.append("   风险提示：已命中站内对照，但站外来源可信度不会因此自动升级。")
        if (
            candidate.source_credibility in {"medium", "low", "unknown"}
            and external_verification.get("verification_status") != "station_matched"
        ):
            lines.append(
                f"   可信度提示：来自 {candidate.source_name or '未知来源'}，"
                "尚未被站内或主流来源交叉验证。"
            )
        lines.append("")
    lines.append("请告诉我是哪一篇，或补充更多关键词。确认后我再继续解释、对比或分析政策信号。")
    return "\n".join(lines).strip()


def extract_anchor_candidates_from_confirmation(text: str) -> list[AnchorCandidate]:
    candidates: list[AnchorCandidate] = []
    current: dict[str, Any] | None = None
    for line in (text or "").splitlines():
        item_match = CONFIRMATION_ITEM_RE.match(line)
        if item_match:
            if current:
                candidates.append(_candidate_from_confirmation_parts(current))
            current = {
                "published_at": item_match.group(2).strip(),
                "source_name": item_match.group(3).strip(),
                "title": item_match.group(4).strip(),
                "source_url_or_evidence_id": "",
            }
            continue
        if current:
            link_match = CONFIRMATION_LINK_RE.match(line)
            if link_match:
                current["source_url_or_evidence_id"] = link_match.group(1).strip()
                continue
            station_match = CONFIRMATION_STATION_RE.match(line)
            if station_match:
                ids: list[str] = []
                titles: list[str] = []
                for raw_pair in station_match.group(1).split(";"):
                    parts = [part.strip() for part in raw_pair.split("|") if part.strip()]
                    if not parts:
                        continue
                    if parts[0].startswith("news:"):
                        ids.append(parts[0])
                        if len(parts) > 1:
                            titles.append(parts[1])
                    else:
                        titles.append(parts[0])
                if ids or titles:
                    current["external_verification"] = {
                        "verification_status": "station_matched",
                        "matched_station_evidence_ids": ids,
                        "matched_station_titles": titles,
                    }
                continue
            warning_match = CONFIRMATION_WARNING_RE.match(line)
            if warning_match:
                external_verification = current.setdefault("external_verification", {})
                if isinstance(external_verification, dict):
                    external_verification["user_warning"] = warning_match.group(1).strip()
    if current:
        candidates.append(_candidate_from_confirmation_parts(current))
    return candidates


def _candidate_from_confirmation_parts(parts: dict[str, Any]) -> AnchorCandidate:
    evidence_ref = parts.get("source_url_or_evidence_id") or ""
    source_name = parts.get("source_name") or ""
    credibility, verification = _source_credibility(source_name, evidence_ref)
    external_verification = parts.get("external_verification")
    if not isinstance(external_verification, dict):
        external_verification = {}
    if external_verification.get("verification_status"):
        verification = str(external_verification.get("verification_status") or verification)
    return AnchorCandidate(
        anchor_id=evidence_ref,
        title=parts.get("title") or "",
        source_name=source_name,
        source_url_or_evidence_id=evidence_ref,
        published_at=parts.get("published_at") or "",
        match_confidence="medium",
        source_credibility=credibility,
        verification_status=verification,
        acquisition_method="rag" if evidence_ref.startswith("news:") else "web",
        match_reasons=["user_selected_from_confirmation"],
        external_verification=external_verification,
    )


def _selection_index(selection_text: str) -> int | None:
    text = selection_text or ""
    match = SELECTION_RE.search(text)
    if not match:
        return None
    token = match.group(1)
    if token.isdigit():
        return int(token) - 1
    ordinal = CHINESE_ORDINALS.get(token)
    if ordinal is None:
        return None
    return ordinal - 1


def confirmed_anchor_from_user_selection(
    selection_text: str,
    candidates: list[AnchorCandidate],
) -> dict[str, Any] | None:
    index = _selection_index(selection_text)
    if index is None or index < 0 or index >= len(candidates):
        return None
    return candidates[index].as_confirmed_metadata()


__all__ = [
    "AnchorCandidate",
    "AnchorResolution",
    "confirmed_anchor_from_user_selection",
    "extract_anchor_candidates_from_confirmation",
    "looks_like_anchor_query",
    "render_anchor_confirmation",
    "resolve_anchor_candidates",
]
