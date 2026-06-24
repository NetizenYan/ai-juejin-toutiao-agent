"""bge-reranker 精排（cross-encoder）。

- 模型**常驻进程**（懒加载单例）；绝不放进 per-request 的 MCP 子进程。
- 召回阶段（Qdrant 向量）取 top-N（如 50），再用 cross-encoder 对 query×doc 精排取 top-k。
- 同步推理用 asyncio.to_thread 包装，避免阻塞事件循环。
- 3.2-C: fusion_rerank 融合 vector_score / cross_encoder_score / light_rule_bonus，
  不让 cross-encoder 完全覆盖原始排序，并输出 score breakdown。
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any

from harness.reranker_api import rerank_with_api

# 模型已预下载到本地 HF 缓存 → 运行时离线加载（快、稳、不依赖网络/镜像）。
# 首次下载请用官方源：HF_ENDPOINT=https://huggingface.co python -m scripts.warmup_reranker
os.environ.setdefault("HF_HUB_OFFLINE", "1")

_RERANKER = None


def _load():
    global _RERANKER
    if _RERANKER is None:
        from sentence_transformers import CrossEncoder
        # 加载时读取（确保 .env 已被 config 加载），默认 v2-m3（中文更强）
        model_name = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
        _RERANKER = CrossEncoder(model_name, max_length=512)
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
    if provider in {"api", "siliconflow"} or api_enabled:
        ranked, _meta = await rerank_with_api(
            query,
            items,
            top_k=top_k,
            model=os.getenv("RERANKER_API_MODEL", "Pro/BAAI/bge-reranker-v2-m3"),
        )
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
