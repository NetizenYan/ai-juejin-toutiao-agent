"""把 news 表的新闻 embedding 进 Qdrant（语义检索索引）。

- 文本 = 标题 + 简介（concise 语义表示）；point id = news.id。
- 维度按 embedding 实际输出确定（不写死），并写入 config/rag_meta.json 做配置锁定。

用法（项目根，需 Qdrant + Ollama 在线）：
    <agent-python> -m scripts.build_news_index            # 全量
    <agent-python> -m scripts.build_news_index --recreate # 重建 collection
"""
from __future__ import annotations

import argparse
import asyncio

from qdrant_client.models import PointStruct
from sqlalchemy import select

from config.ai_conf import settings, get_embedding_client
from config.db_conf import AsyncSessionLocal, async_engine
from config.vector_conf import get_qdrant, ensure_collection, save_meta, COLLECTION
from models.news import News

BATCH = 64


async def _embed(client, texts: list[str]) -> list[list[float]]:
    resp = await client.embeddings.create(model=settings.embedding_model, input=texts)
    return [d.embedding for d in resp.data]


async def main(recreate: bool):
    emb_client = get_embedding_client()
    # 探测维度（不写死）
    dim = len((await _embed(emb_client, ["维度探测"]))[0])
    print(f"embedding={settings.embedding_model} dim={dim} collection={COLLECTION}")

    qdrant = get_qdrant()
    await ensure_collection(qdrant, dim, recreate=recreate)

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(News.id, News.title, News.description))).all()
    print(f"待索引 {len(rows)} 条")

    total = 0
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        texts = [f"{(r.title or '')}\n{(r.description or '')}".strip() for r in chunk]
        vectors = await _embed(emb_client, texts)
        points = [
            PointStruct(id=int(r.id), vector=vec, payload={
                "news_id": int(r.id),
                "title": r.title,
                "summary": (r.description or "")[:300],
            })
            for r, vec in zip(chunk, vectors)
        ]
        await qdrant.upsert(collection_name=COLLECTION, points=points)
        total += len(points)
        if total % (BATCH * 8) == 0 or total >= len(rows):
            print(f"  已索引 {total}/{len(rows)}")

    save_meta(settings.embedding_model, dim)
    await async_engine.dispose()
    print(f"完成：索引 {total} 条，meta 已写入")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--recreate", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.recreate))
