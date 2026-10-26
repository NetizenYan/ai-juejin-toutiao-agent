"""bge-reranker 精排（cross-encoder）。

- 模型**常驻进程**（懒加载单例）；绝不放进 per-request 的 MCP 子进程。
- 召回阶段（Qdrant 向量）取 top-N（如 50），再用 cross-encoder 对 query×doc 精排取 top-k。
- 同步推理用 asyncio.to_thread 包装，避免阻塞事件循环。
- 3.2-C: fusion_rerank 融合 vector_score / cross_encoder_score / light_rule_bonus，
  不让 cross-encoder 完全覆盖原始排序，并输出 score breakdown。
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any

from harness.reranker_api import rerank_with_api

logger = logging.getLogger(__name__)

# 本地 cross-encoder 默认只读本地 HF 缓存（RERANKER_LOCAL_FILES_ONLY=true），不联网下载。
# 之前在导入时全局设置 HF_HUB_OFFLINE=1：它进入后端进程环境，又被 web MCP 子进程继承，
# 让 PaddleOCR 在新机器上无法从 HuggingFace 下载模型。现在只作用于这一次模型加载。
_RERANKER = None
_LOAD_ERROR: str | None = None


def _load():
    """Lazily load the local cross-encoder once; a failure is remembered instead of retried per request."""
    global _RERANKER, _LOAD_ERROR
    if _RERANKER is not None:
        return _RERANKER
    if _LOAD_ERROR is not None:
        raise RuntimeError(_LOAD_ERROR)
    try:
        from sentence_transformers import CrossEncoder
        # 加载时读取（确保 .env 已被 config 加载），默认 v2-m3（中文更强）
        model_name = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
        local_only = (os.getenv("RERANKER_LOCAL_FILES_ONLY") or "true").strip().lower() in {"1", "true", "yes", "on"}
        _RERANKER = CrossEncoder(model_name, max_length=512, local_files_only=local_only)
    except Exception as exc:  # noqa: BLE001 - missing package or model: rerank falls back to recall order
        _LOAD_ERROR = f"local reranker unavailable: {type(exc).__name__}: {exc}"
        logger.warning("%s; using recall order until restart", _LOAD_ERROR)
        raise RuntimeError(_LOAD_ERROR) from exc
    return _RERANKER


def _doc_text(item: dict) -> str:
    return f"{item.get('title') or ''} {item.get('summary') or ''}".strip()


def _sync_rerank(query: str, items: list[dict], top_k: int) -> list[dict]:
    model = _load()
    pairs = [(query, _doc_text(it)) for it in items]
    scores = model.predict(pairs)
    ranked = sorted(zip(items, scores), key=lambda x: float(x[1]), reverse=True)
    out: list[dict] = []
    for it, sc in ranked[:top_k]:
        it = dict(it)
        it["rerank_score"] = round(float(sc), 4)
        out.append(it)
    return out


async def rerank(query: str, items: list[dict], top_k: int = 5) -> list[dict]:
    """对召回的候选做精排，返回 top_k。失败则降级返回原顺序前 top_k。"""
    if not items or not query:
        return items[:top_k]
    provider = (os.getenv("RERANKER_PROVIDER") or "").strip().lower()
    api_enabled = (os.getenv("RERANKER_API_ENABLED") or "").strip().lower() in {"1", "true", "yes", "on"}
    if provider in {"api", "siliconflow", "hf_api"} or api_enabled:
        hf_api = provider == "hf_api"
        ranked, _meta = await rerank_with_api(
            query,
            items,
            top_k=top_k,
            base_url=os.getenv("RERANKER_API_BASE_URL") or None,
            model=os.getenv(
                "RERANKER_API_MODEL",
                "BAAI/bge-reranker-v2-m3" if hf_api else "Pro/BAAI/bge-reranker-v2-m3",
            ),
            api_format="hf_api" if hf_api else "siliconflow",
        )
        if not _meta.get("used"):
            # Falling back to recall order silently hid an hf-api 422 for every real query.
            logger.warning("rerank api fallback to recall order: %s", _meta.get("reason"))
        return ranked
    try:
        return await asyncio.to_thread(_sync_rerank, query, items, top_k)
    except Exception:  # noqa: BLE001 - 重排失败不应中断回答，降级用召回顺序
        return items[:top_k]


_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_ASCII_TERM_RE = re.compile(r"[a-zA-Z0-9]+")
_KNOWN_ENTITY_TERMS = (
    "新质生产力",
    "高质量发展",
    "科技创新",
    "产业升级",
    "产业链",
    "制造业",
    "高技术制造业",
    "现代化产业体系",
    "半导体",
    "新能源",
    "经济日报",
    "人民日报",
    "新闻联播",
)

_DISTRACTOR_NEGATIVE_TERMS = (
    "销量增长",
    "新能源汽车",
    "GDP增速",
    "只讲",
)

_SOURCE_ALIASES = {
    "经济日报": ("jjrb", "经济日报"),
    "人民日报": ("rmrb", "人民日报"),
    "新闻联播": ("新闻联播",),
    "央视": ("央视", "新闻联播"),
    "新华社": ("新华社",),
}


def _light_rule_bonus(query: str, item: dict[str, Any]) -> float:
    """Rule-based bonus used by fusion rerank; mirrors eval light_rule_rerank signals."""
    text = query or ""
    if not text:
        return 0.0
    terms = [t for t in _KNOWN_ENTITY_TERMS if t in text]
    title = str(item.get("title") or "")
    summary = str(item.get("summary") or item.get("text") or "")
    haystack = title + "\n" + summary
    bonus = 0.0
    for term in terms:
        if term in title:
            bonus += 3.0 if len(term) >= 4 else 1.0
        elif term in haystack:
            bonus += 1.0
    if title and title in text:
        bonus += 8.0
    for source_name, aliases in _SOURCE_ALIASES.items():
        if source_name in text:
            item_source = str(item.get("source") or "")
            if any(a in item_source or a == item_source for a in aliases):
                bonus += 2.0
                break
    if any(neg in text for neg in _DISTRACTOR_NEGATIVE_TERMS):
        if not any(term in haystack for term in _KNOWN_ENTITY_TERMS[:4]):
            bonus -= 2.0
    return bonus


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    low = min(values)
    high = max(values)
    if high == low:
        return [1.0 if high > 0 else 0.0 for _ in values]
    return [(v - low) / (high - low) for v in values]


def _sync_fusion_rerank(
    query: str,
    items: list[dict],
    top_k: int,
    *,
    cross_encoder_weight: float,
    vector_weight: float,
    light_bonus_weight: float,
) -> list[dict]:
    model = _load()
    pairs = [(query, _doc_text(it)) for it in items]
    ce_scores = [float(s) for s in model.predict(pairs)]
    vec_scores = [float(it.get("score") or 0.0) for it in items]
    light_bonuses = [_light_rule_bonus(query, it) for it in items]

    norm_ce = _normalize(ce_scores)
    norm_vec = _normalize(vec_scores)
    light_arr = [b for b in light_bonuses]
    norm_light = _normalize(light_arr) if any(b > 0 for b in light_arr) else [0.0 for _ in light_bonuses]

    ranked: list[dict] = []
    for index, item in enumerate(items):
        copy = dict(item)
        fusion = (
            vector_weight * norm_vec[index]
            + cross_encoder_weight * norm_ce[index]
            + light_bonus_weight * norm_light[index]
        )
        breakdown = {
            "vector_score_norm": round(norm_vec[index], 4),
            "cross_encoder_score_norm": round(norm_ce[index], 4),
            "light_rule_bonus": round(light_bonuses[index], 4),
            "light_rule_bonus_norm": round(norm_light[index], 4),
            "fusion_score": round(fusion, 4),
        }
        copy["fusion_score"] = round(fusion, 4)
        copy["rerank_score"] = round(ce_scores[index], 4)
        copy["score_breakdown"] = breakdown
        ranked.append(copy)

    ranked.sort(
        key=lambda it: (float(it["fusion_score"]), float(it.get("rerank_score") or 0.0)),
        reverse=True,
    )
    return ranked[:top_k]


async def fusion_rerank(
    query: str,
    items: list[dict],
    top_k: int = 5,
    *,
    cross_encoder_weight: float = 0.40,
    vector_weight: float = 0.40,
    light_bonus_weight: float = 0.20,
) -> list[dict]:
    """Fusion rerank combining vector score, cross-encoder score and light rule bonus.

    The cross-encoder weight is capped below 0.5 by default so it cannot
    completely override the original vector ranking. Falls back to vector
    order when the cross-encoder is unavailable.
    """
    if not items or not query:
        return items[:top_k]
    try:
        return await asyncio.to_thread(
            _sync_fusion_rerank,
            query,
            items,
            top_k,
            cross_encoder_weight=cross_encoder_weight,
            vector_weight=vector_weight,
            light_bonus_weight=light_bonus_weight,
        )
    except Exception:  # noqa: BLE001 - fusion 失败降级用 light_rule_rerank 顺序
        ranked = list(items)
        ranked.sort(
            key=lambda it: (float(it.get("score") or 0.0) + _light_rule_bonus(query, it)),
            reverse=True,
        )
        return ranked[:top_k]


async def warmup() -> None:
    await rerank("预热", [{"title": "预热", "summary": "预热文本"}], top_k=1)
