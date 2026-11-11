"""Pluggable OCR providers for external screenshot ingestion."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class OCRResult:
    text: str
    confidence: float
    title: str = ""
    engine: str = "unknown"
    lines: list[dict[str, Any]] = field(default_factory=list)
    raw_payload: Any = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "confidence": self.confidence,
            "title": self.title,
            "engine": self.engine,
            "lines": self.lines,
        }


class OCRProvider(Protocol):
    async def extract(self, image_path: str) -> OCRResult:
        """Extract OCR text from an image path."""


class PaddleOCRProvider:
    """Lazy PaddleOCR adapter.

    The dependency is imported only when extract() is called, so ordinary tests
    and deployments can keep PaddleOCR optional until the OCR tool is enabled.
    """

    engine_name = "paddleocr"

    def __init__(
        self,
        *,
        factory: Any | None = None,
        lang: str = "ch",
        use_angle_cls: bool = True,
        **ocr_kwargs: Any,
    ) -> None:
        self._factory = factory
        self.lang = lang
        self.use_angle_cls = use_angle_cls
        self.ocr_kwargs = dict(ocr_kwargs)
        self._engine: Any | None = None

    async def extract(self, image_path: str) -> OCRResult:
        return await asyncio.to_thread(self._extract_sync, image_path)

    def _extract_sync(self, image_path: str) -> OCRResult:
        engine = self._get_engine()
        raw = self._run_engine(engine, image_path)
        return self._normalize(raw)

    def _get_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        kwargs = {"lang": self.lang}
        kwargs.update(self.ocr_kwargs)
        if "use_textline_orientation" not in kwargs:
            kwargs["use_angle_cls"] = self.use_angle_cls
        if self._factory is not None:
            self._engine = self._factory(**kwargs)
            return self._engine
        try:
            from paddleocr import PaddleOCR  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "PaddleOCR is not installed. Install paddleocr in the OCR runtime environment."
            ) from exc
        self._engine = PaddleOCR(**kwargs)
        return self._engine

    def _run_engine(self, engine: Any, image_path: str) -> Any:
        if hasattr(engine, "predict"):
            return engine.predict(image_path)
        if hasattr(engine, "ocr"):
            try:
                return engine.ocr(image_path, cls=self.use_angle_cls)
            except TypeError:
                return engine.ocr(image_path)
        raise RuntimeError("PaddleOCR engine does not expose ocr() or predict().")

    def _normalize(self, raw: Any) -> OCRResult:
        lines = _collect_ocr_lines(raw)
        text_lines = [str(line.get("text") or "").strip() for line in lines]
        text_lines = [line for line in text_lines if line]
        confidences = [
            float(line["confidence"])
            for line in lines
            if _is_number(line.get("confidence"))
        ]
        confidence = sum(confidences) / len(confidences) if confidences else 0.0
        title = text_lines[0] if text_lines else ""
        return OCRResult(
            text="\n".join(text_lines),
            confidence=confidence,
            title=title,
            engine=self.engine_name,
            lines=lines,
            raw_payload=raw,
        )


class UnlimitedOCRProvider:
    """Future GPU/VLM OCR provider placeholder.

    This keeps the provider registry stable without silently pretending that a
    local Unlimited-OCR service exists.
    """

    engine_name = "unlimited_ocr"

    def __init__(self, *, endpoint_url: str = "", model: str = "Unlimited-OCR") -> None:
        self.endpoint_url = endpoint_url.strip()
        self.model = model

    async def extract(self, image_path: str) -> OCRResult:
        if not self.endpoint_url:
            raise RuntimeError("Unlimited-OCR provider is not configured.")
        raise NotImplementedError("Unlimited-OCR HTTP extraction is reserved for the GPU provider phase.")


def create_ocr_provider(name: str = "paddleocr", **kwargs: Any) -> OCRProvider:
    normalized = (name or "paddleocr").strip().lower().replace("-", "_")
    if normalized in {"paddle", "paddleocr", "paddle_ocr", "default"}:
        return PaddleOCRProvider(**kwargs)
    if normalized in {"unlimited", "unlimited_ocr", "unlimitedocr"}:
        return UnlimitedOCRProvider(**kwargs)
    raise ValueError(f"Unknown OCR provider: {name}")


def _collect_ocr_lines(raw: Any) -> list[dict[str, Any]]:
    parsed = _parse_line(raw)
    if parsed is not None:
        return [parsed]
    if isinstance(raw, dict):
        v3_lines = _parse_v3_result(raw)
        if v3_lines:
            return v3_lines
        for key in ("lines", "data", "result", "ocr_result", "rec_texts"):
            if key in raw:
                return _collect_ocr_lines(raw[key])
        return []
    if isinstance(raw, (list, tuple)):
        lines: list[dict[str, Any]] = []
        for item in raw:
            lines.extend(_collect_ocr_lines(item))
        return lines
    return []


def _parse_v3_result(value: dict[str, Any]) -> list[dict[str, Any]]:
    payload = value.get("res") if isinstance(value.get("res"), dict) else value
    texts = payload.get("rec_texts")
    if not isinstance(texts, list):
        return []
    scores = payload.get("rec_scores") if isinstance(payload.get("rec_scores"), list) else []
    boxes = []
    for key in ("rec_polys", "rec_boxes", "dt_polys"):
        if isinstance(payload.get(key), list):
            boxes = payload[key]
            break
    lines: list[dict[str, Any]] = []
    for index, text in enumerate(texts):
        if not isinstance(text, str) or not text.strip():
            continue
        item: dict[str, Any] = {"text": text.strip()}
        if index < len(scores) and _is_number(scores[index]):
            item["confidence"] = float(scores[index])
        if index < len(boxes):
            item["box"] = _json_safe(boxes[index])
        lines.append(item)
    return lines


def _parse_line(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        text = value.get("text") or value.get("rec_text") or value.get("label")
        confidence = value.get("confidence") or value.get("score") or value.get("rec_score")
        if isinstance(text, str):
            item: dict[str, Any] = {"text": text.strip()}
            if _is_number(confidence):
                item["confidence"] = float(confidence)
            if "box" in value:
                item["box"] = _json_safe(value["box"])
            return item
        rec_texts = value.get("rec_texts")
        rec_scores = value.get("rec_scores") or []
        if isinstance(rec_texts, list):
            return None
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    if isinstance(value[0], str) and _is_number(value[1]):
        return {"text": value[0].strip(), "confidence": float(value[1])}
    candidate = value[1]
    if isinstance(candidate, (list, tuple)) and len(candidate) >= 2:
        text, confidence = candidate[0], candidate[1]
        if isinstance(text, str):
            item = {"text": text.strip()}
            if _is_number(confidence):
                item["confidence"] = float(confidence)
            if value[0]:
                item["box"] = _json_safe(value[0])
            return item
    return None


def _json_safe(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _is_number(value: Any) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


__all__ = [
    "OCRProvider",
    "OCRResult",
    "PaddleOCRProvider",
    "UnlimitedOCRProvider",
    "create_ocr_provider",
]
