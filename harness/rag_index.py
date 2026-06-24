"""RAG 增量索引：把新文档 embed 后增量写入 Qdrant（供步骤②web 回灌 / 步骤③增量 embed 复用）。

- upsert_news_rows：对给定 (id,title,summary) 批量 embed + upsert（增量，不重建）。
- add_external_doc：插入一条 News（如 web 抓取内容）+ 立即 embed 入库，返回 news_id。
"""
from __future__ import annotations

from datetime import datetime

from qdrant_client.models import PointStruct
from sqlalchemy import select

from config.ai_conf import settings, get_embedding_client
from config.db_conf import AsyncSessionLocal
from config.vector_conf import get_qdrant, ensure_collection, COLLECTION
from models.news import News


async def _embed(texts: list[str]) -> list[list[float]]:
    client = get_embedding_client()
    resp = await client.embeddings.create(model=settings.embedding_model, input=texts)
    return [d.embedding for d in resp.data]


async def upsert_news_rows(rows: list[tuple[int, str, str]], batch: int = 64) -> int:
    """rows: [(news_id, title, summary), ...] → 增量 embed + upsert 到 Qdrant。返回条数。"""
    if not rows:
        return 0
    qdrant = get_qdrant()
    total = 0
    for i in range(0, len(rows), batch):
        chunk = rows[i:i + batch]
        texts = [f"{(t or '')}\n{(s or '')}".strip() for (_id, t, s) in chunk]
        vectors = await _embed(texts)
        points = [
            PointStruct(id=int(nid), vector=vec, payload={"news_id": int(nid), "title": t, "summary": (s or "")[:300]})
            for (nid, t, s), vec in zip(chunk, vectors)
        ]
        await qdrant.upsert(collection_name=COLLECTION, points=points)
        total += len(points)
    return total


async def add_external_doc(title: str, text: str, source: str = "web",
                           url: str | None = None, category_id: int = 1) -> int:
    """插入一条外部文档为 News 并立即 embed 入库（web 回灌）。按标题去重。返回 news_id。"""
    title = (title or text[:30] or "外部文档").strip()[:255]
    summary = (text or "").replace("\n", " ").strip()[:500]
    content = (text or "")[:20000] + (f"\n\n原文：{url}" if url else "") + f"\n（来源：{source}）"

    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(News.id).where(News.title == title))
        nid = existing.scalar_one_or_none()
        if nid is None:
            row = News(title=title, description=summary, content=content, image=None,
                       author=source, category_id=category_id, views=0, publish_time=datetime.now())
            db.add(row)
            await db.commit()
            await db.refresh(row)
            nid = row.id

    await upsert_news_rows([(nid, title, summary)])
    return nid
