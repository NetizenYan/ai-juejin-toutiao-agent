"""External evidence staging records for B-v3 tools/OCR workflows."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from config.ai_conf import settings
from harness.ocr_providers import OCRProvider, OCRResult
from harness.rag_index import add_external_doc


AddExternalDocFn = Callable[..., Awaitable[int]]
CaptureScreenshotFn = Callable[[str], Awaitable[dict[str, Any]]]
ExtractOcrTextFn = Callable[[str], Awaitable[dict[str, Any] | str]]


_OCR_NOISE_EXACT = {
    "cookie settings",
    "accept all",
    "accept cookies",
    "sign in",
    "log in",
    "login",
    "share",
    "menu",
    "privacy",
    "terms",
    "related articles",
    "recommended",
    "subscribe",
}
_OCR_NOISE_RE = re.compile(
    r"("
    r"cookie|privacy|terms|subscribe|sign\s*in|log\s*in|related\s+articles|"
    r"登录|登陆|注册|分享|评论|广告|打开\s*app|打开APP|下载|关注|阅读全文|相关推荐|更多"
    r")",
    re.IGNORECASE,
)
_TERM_STOPWORDS = {
    "the",
    "and",
    "for",
    "from",
    "with",
    "that",
    "this",
    "will",
    "says",
    "report",
    "station",
    "external",
    "ocr",
    "lead",
    "source",
    "unknown",
    "news",
}


@dataclass(frozen=True)
class ExternalEvidenceVerification:
    verification_status: str
    matched: bool
    matched_station_evidence_ids: list[str] = field(default_factory=list)
    matched_station_titles: list[str] = field(default_factory=list)
    overlap_terms: list[str] = field(default_factory=list)
    overlap_count: int = 0
    verification_reason: str = ""
    user_warning: str = ""
    method: str = "simple_term_overlap"

    def as_metadata(self) -> dict[str, Any]:
        return {
            "verification_status": self.verification_status,
            "matched": self.matched,
            "matched_station_evidence_ids": self.matched_station_evidence_ids,
            "matched_station_titles": self.matched_station_titles,
            "overlap_terms": self.overlap_terms,
            "overlap_count": self.overlap_count,
            "verification_reason": self.verification_reason,
            "user_warning": self.user_warning,
            "method": self.method,
        }


@dataclass(frozen=True)
class OcrDenoiseResult:
    raw_text: str
    clean_text: str
    raw_text_hash: str
    raw_text_chars: int
    clean_text_chars: int
    removed_line_count: int
    duplicate_line_count: int
    truncated: bool
    status: str


@dataclass(frozen=True)
class OcrCaptureRecord:
    source_url: str
    source_name: str
    captured_at: str
    image_path: str
    raw_image_hash: str
    ocr_text: str
    ocr_confidence: float
    title: str = ""
    ocr_engine: str = "unknown"
    ocr_lines: list[dict[str, Any]] = field(default_factory=list)
    ingest_status: str = "pending"
    source_credibility: str = "low"
    verification_status: str = "unverified"
    raw_ocr_text_hash: str = ""
    raw_ocr_text_chars: int = 0
    clean_ocr_text_chars: int = 0
    denoise_removed_line_count: int = 0
    duplicate_ocr_line_count: int = 0
    ocr_denoise_status: str = "not_applied"
    staging_status: str = "staged"

    def to_candidate_item(self) -> dict:
        raw_text_hash = self.raw_ocr_text_hash or _hash_text(self.ocr_text)
        raw_text_chars = self.raw_ocr_text_chars or len(self.ocr_text)
        clean_text_chars = self.clean_ocr_text_chars or len(self.ocr_text)
        return {
            "id": self.source_url,
            "source_url": self.source_url,
            "url": self.source_url,
            "source": self.source_name,
            "title": self.title or "站外 OCR 线索",
            "summary": self.ocr_text,
            "text": self.ocr_text,
            "captured_at": self.captured_at,
            "image_path": self.image_path,
            "raw_image_hash": self.raw_image_hash,
            "raw_ocr_text_hash": raw_text_hash,
            "raw_ocr_text_chars": raw_text_chars,
            "clean_ocr_text_chars": clean_text_chars,
            "denoise_removed_line_count": self.denoise_removed_line_count,
            "duplicate_ocr_line_count": self.duplicate_ocr_line_count,
            "ocr_denoise_status": self.ocr_denoise_status,
            "staging_status": self.staging_status,
            "ocr_confidence": self.ocr_confidence,
            "ocr_engine": self.ocr_engine,
            "ocr_lines": self.ocr_lines,
            "acquisition_method": "ocr_screenshot",
            "source_credibility": self.source_credibility,
            "verification_status": self.verification_status,
            "ingest_status": self.ingest_status,
        }


def _external_ocr_source_name(source_name: str) -> str:
    normalized = (source_name or "unknown").strip() or "unknown"
    return f"external_ocr:{normalized}"


def _hash_text(text: str) -> str:
    return "sha256:" + hashlib.sha256((text or "").encode("utf-8", errors="ignore")).hexdigest()


def _normalize_ocr_line(line: str) -> str:
    return re.sub(r"\s+", " ", line or "").strip()


def _signal_char_count(text: str) -> int:
    return sum(1 for char in text or "" if char.isalnum() or "\u4e00" <= char <= "\u9fff")


def _item_text(item: dict[str, Any]) -> str:
    return "\n".join(
        str(item.get(key) or "")
        for key in ("title", "summary", "snippet", "text", "chunk_text", "source")
    )


def _station_evidence_id(item: dict[str, Any]) -> str:
    evidence_id = str(item.get("evidence_id") or "").strip()
    if evidence_id:
        return evidence_id
    item_id = item.get("id")
    if item_id is None:
        return ""
    value = str(item_id)
    return value if value.startswith("news:") else f"news:{value}"


def _extract_verification_terms(text: str) -> set[str]:
    value = re.sub(r"\s+", " ", text or "").strip().lower()
    terms = {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9_\-]{2,}", value)
        if token not in _TERM_STOPWORDS
    }
    cjk_text = "".join(re.findall(r"[\u4e00-\u9fff]+", text or ""))
    max_cjk_len = min(len(cjk_text), 200)
    cjk_text = cjk_text[:max_cjk_len]
    for size in range(2, 7):
        for index in range(0, max(0, len(cjk_text) - size + 1)):
            terms.add(cjk_text[index:index + size])
    return {term for term in terms if term}


def _source_label(item: dict[str, Any]) -> str:
    return str(item.get("source") or item.get("source_name") or "unknown").strip() or "unknown"


def verify_external_evidence(
    external_item: dict[str, Any],
    station_items: list[dict[str, Any]] | None,
    *,
    min_overlap_terms: int = 2,
) -> ExternalEvidenceVerification:
    """Compare one external/OCR item against station-internal candidates."""
    source = _source_label(external_item)
    ocr_terms = _extract_verification_terms(_item_text(external_item))
    if len(ocr_terms) < max(1, min_overlap_terms):
        return ExternalEvidenceVerification(
            verification_status="low_signal",
            matched=False,
            verification_reason="OCR 文本有效信号不足，无法进行可靠站内对照。",
            user_warning=f"来自 {source} 的 OCR 线索信号不足，不能作为确定事实依据。",
        )
    if not station_items:
        return ExternalEvidenceVerification(
            verification_status="unverified",
            matched=False,
            verification_reason="没有可用于对照的站内候选。",
            user_warning=f"来自 {source} 的站外 OCR 线索尚未命中站内对照，可信度较低。",
        )

    best: tuple[int, list[str], dict[str, Any]] | None = None
    for station_item in station_items or []:
        if not isinstance(station_item, dict):
            continue
        overlap = sorted(ocr_terms & _extract_verification_terms(_item_text(station_item)))
        candidate = (len(overlap), overlap, station_item)
        if best is None or candidate[0] > best[0]:
            best = candidate

    if best is None or best[0] < max(1, min_overlap_terms):
        return ExternalEvidenceVerification(
            verification_status="unverified",
            matched=False,
            verification_reason="站内候选与站外 OCR 线索重合不足。",
            user_warning=f"来自 {source} 的站外 OCR 线索尚未被站内新闻交叉验证，可信度较低。",
        )

    overlap_count, overlap_terms, station_item = best
    station_ref = _station_evidence_id(station_item)
    station_title = str(station_item.get("title") or "")
    if station_item.get("external_conflict") or str(station_item.get("verification_status") or "").lower() in {
        "conflict",
        "contradicted",
    }:
        return ExternalEvidenceVerification(
            verification_status="conflict",
            matched=False,
            matched_station_evidence_ids=[station_ref] if station_ref else [],
            matched_station_titles=[station_title] if station_title else [],
            overlap_terms=overlap_terms,
            overlap_count=overlap_count,
            verification_reason="站内候选与站外 OCR 线索存在冲突标记。",
            user_warning=f"来自 {source} 的站外 OCR 线索与站内对照存在冲突，不能作为确定事实依据。",
        )

    return ExternalEvidenceVerification(
        verification_status="station_matched",
        matched=True,
        matched_station_evidence_ids=[station_ref] if station_ref else [],
        matched_station_titles=[station_title] if station_title else [],
        overlap_terms=overlap_terms,
        overlap_count=overlap_count,
        verification_reason="站外 OCR 线索命中站内候选，可作为对照线索，但不改变原始来源可信度。",
        user_warning=f"来自 {source} 的站外 OCR 线索已命中站内对照；仍需按站外来源标注可信度。",
    )


def _is_noise_ocr_line(line: str) -> bool:
    value = _normalize_ocr_line(line)
    if not value:
        return True
    compact = re.sub(r"\s+", "", value)
    lowered = value.casefold()
    if lowered in _OCR_NOISE_EXACT:
        return True
    if _OCR_NOISE_RE.search(value):
        return True
    signal_chars = _signal_char_count(value)
    if signal_chars < 4:
        return True
    if signal_chars / max(1, len(compact)) < 0.35:
        return True
    return False


def denoise_ocr_text(
    text: str,
    *,
    max_chars: int | None = None,
    min_signal_chars: int | None = None,
) -> OcrDenoiseResult:
    raw_text = str(text or "")
    raw_hash = _hash_text(raw_text)
    clean_lines: list[str] = []
    seen: set[str] = set()
    removed = 0
    duplicates = 0
    for raw_line in raw_text.splitlines():
        line = _normalize_ocr_line(raw_line)
        if not line:
            continue
        dedupe_key = line.casefold()
        if dedupe_key in seen:
            duplicates += 1
            continue
        if _is_noise_ocr_line(line):
            removed += 1
            continue
        seen.add(dedupe_key)
        clean_lines.append(line)

    clean_text = "\n".join(clean_lines).strip()
    limit = max(1, int(max_chars if max_chars is not None else settings.ocr_clean_max_chars))
    truncated = len(clean_text) > limit
    if truncated:
        clean_text = clean_text[:limit].rstrip()
    signal_min = max(1, int(min_signal_chars if min_signal_chars is not None else settings.ocr_min_clean_chars))
    status = "cleaned" if _signal_char_count(clean_text) >= signal_min else "rejected_no_signal"
    return OcrDenoiseResult(
        raw_text=raw_text,
        clean_text=clean_text,
        raw_text_hash=raw_hash,
        raw_text_chars=len(raw_text),
        clean_text_chars=len(clean_text),
        removed_line_count=removed,
        duplicate_line_count=duplicates,
        truncated=truncated,
        status=status,
    )


async def index_ocr_capture_record(
    record: OcrCaptureRecord,
    *,
    add_external_doc_fn: AddExternalDocFn = add_external_doc,
    category_id: int = 1,
) -> dict:
    """Index an OCR-only external capture while preserving its evidence policy."""
    news_id = await add_external_doc_fn(
        title=record.title,
        text=record.ocr_text,
        source=_external_ocr_source_name(record.source_name),
        url=record.source_url,
        category_id=category_id,
    )
    item = record.to_candidate_item()
    item.update(
        {
            "id": news_id,
            "news_id": news_id,
            "evidence_id": f"news:{news_id}",
            "source": record.source_name,
            "source_url": record.source_url,
            "url": record.source_url,
            "ingest_status": "indexed",
            "source_credibility": record.source_credibility,
            "verification_status": record.verification_status,
            "acquisition_method": "ocr_screenshot",
        }
    )
    return item


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _fallback_image_hash(image_path: str, source_url: str) -> str:
    value = f"{image_path}|{source_url}".encode("utf-8", errors="ignore")
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _ocr_payload_text(payload: dict[str, Any] | str) -> str:
    if isinstance(payload, OCRResult):
        return payload.text.strip()
    if isinstance(payload, str):
        return payload.strip()
    return str(payload.get("text") or payload.get("ocr_text") or "").strip()


def _ocr_payload_confidence(payload: dict[str, Any] | str) -> float:
    if isinstance(payload, OCRResult):
        return float(payload.confidence or 0.0)
    if isinstance(payload, str):
        return 0.0
    try:
        return float(payload.get("confidence") or payload.get("ocr_confidence") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _ocr_payload_title(payload: dict[str, Any] | str) -> str:
    if isinstance(payload, OCRResult):
        return payload.title.strip()
    if isinstance(payload, str):
        return ""
    return str(payload.get("title") or "").strip()


def _ocr_payload_engine(payload: dict[str, Any] | str) -> str:
    if isinstance(payload, OCRResult):
        return payload.engine.strip() or "unknown"
    if isinstance(payload, str):
        return "unknown"
    return str(payload.get("engine") or payload.get("ocr_engine") or "unknown").strip() or "unknown"


def _ocr_payload_lines(payload: dict[str, Any] | str) -> list[dict[str, Any]]:
    if isinstance(payload, OCRResult):
        return list(payload.lines)
    if isinstance(payload, str):
        return []
    lines = payload.get("lines") or payload.get("ocr_lines") or []
    return list(lines) if isinstance(lines, list) else []


async def ingest_url_via_ocr(
    source_url: str,
    *,
    source_name: str,
    capture_screenshot_fn: CaptureScreenshotFn,
    extract_ocr_text_fn: ExtractOcrTextFn | None = None,
    ocr_provider: OCRProvider | None = None,
    add_external_doc_fn: AddExternalDocFn = add_external_doc,
    category_id: int = 1,
    min_ocr_confidence: float = 0.35,
) -> dict:
    """Capture an external page via screenshot OCR and index usable text as a low-trust lead."""
    capture = await capture_screenshot_fn(source_url)
    image_path = str(capture.get("image_path") or capture.get("path") or "").strip()
    record_source_url = str(capture.get("final_url") or source_url).strip() or source_url
    raw_image_hash = str(capture.get("raw_image_hash") or capture.get("image_hash") or "").strip()
    if not raw_image_hash:
        raw_image_hash = _fallback_image_hash(image_path, record_source_url)

    if ocr_provider is not None:
        ocr_payload = await ocr_provider.extract(image_path or source_url)
    elif extract_ocr_text_fn is not None:
        ocr_payload = await extract_ocr_text_fn(image_path or source_url)
    else:
        raise ValueError("ingest_url_via_ocr requires extract_ocr_text_fn or ocr_provider.")
    ocr_text = _ocr_payload_text(ocr_payload)
    ocr_confidence = _ocr_payload_confidence(ocr_payload)
    title = _ocr_payload_title(ocr_payload)
    ocr_engine = _ocr_payload_engine(ocr_payload)
    ocr_lines = _ocr_payload_lines(ocr_payload)
    denoised = denoise_ocr_text(ocr_text)
    if not ocr_text or ocr_confidence < min_ocr_confidence:
        status = "rejected"
        staging_status = "staged_rejected"
    elif denoised.status != "cleaned":
        status = "rejected_noisy_ocr"
        staging_status = "staged_rejected"
    else:
        status = "pending"
        staging_status = "staged_clean"
    record = OcrCaptureRecord(
        source_url=record_source_url,
        source_name=source_name,
        captured_at=str(capture.get("captured_at") or _utc_now_iso()),
        image_path=image_path,
        raw_image_hash=raw_image_hash,
        title=title,
        ocr_text=denoised.clean_text,
        ocr_confidence=ocr_confidence,
        ocr_engine=ocr_engine,
        ocr_lines=ocr_lines,
        ingest_status=status,
        raw_ocr_text_hash=denoised.raw_text_hash,
        raw_ocr_text_chars=denoised.raw_text_chars,
        clean_ocr_text_chars=denoised.clean_text_chars,
        denoise_removed_line_count=denoised.removed_line_count,
        duplicate_ocr_line_count=denoised.duplicate_line_count,
        ocr_denoise_status=denoised.status,
        staging_status=staging_status,
    )
    if status != "pending":
        return record.to_candidate_item()
    return await index_ocr_capture_record(
        record,
        add_external_doc_fn=add_external_doc_fn,
        category_id=category_id,
    )


__all__ = [
    "ExternalEvidenceVerification",
    "OcrCaptureRecord",
    "OcrDenoiseResult",
    "denoise_ocr_text",
    "index_ocr_capture_record",
    "ingest_url_via_ocr",
    "verify_external_evidence",
]
