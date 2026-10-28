"""父子索引：把每条新闻全文切 chunk → embed → 写入 Qdrant 子级 collection。

- 父=news_id（评测/去重/引用），子=chunk（检索/精排/证据）。
- chunk embedding 文本 = 标题 + 日期 + 来源 + chunk 正文（给模板化文本做解耦、利于过滤）。
- payload 带 news_id/chunk_index/title/source/publish_ts/chunk_text，供聚合到 parent + 时间衰减。
- point id = news_id * 1000 + chunk_index（唯一整数）。

用法：<agent-python> -X utf8 -m scripts.build_chunk_index [--recreate] [--min-chunk N]

--min-chunk N 只补 chunk_index >= N 的块（已有的块 id 和向量不变）。2026-10-28 前上限是 8 块
（约前 3960 字），新闻联播整日文稿有 47% 的文字没进索引；补建用 --min-chunk 8。
向量必须和已有块同源：已有块是本地 Ollama bge-m3 生成的，补建时
EMBEDDING_BASE_URL=http://ollama:11434/v1 EMBEDDING_MODEL=bge-m3。
"""
from __future__ import annotations

import argparse
import asyncio

from openai import BadRequestError

from qdrant_client.models import PointStruct, Distance, VectorParams
from sqlalchemy import select

from config.ai_conf import settings, get_embedding_client
from config.db_conf import AsyncSessionLocal, async_engine
from config.vector_conf import get_qdrant, CHUNK_COLLECTION, ensure_payload_indexes, save_meta
from models.news import News
from harness.chunking import chunk_text

BATCH = 64
# point id = news_id * 1000 + chunk_index, so a document may have at most 1000 chunks; the longest
# transcript needs 46.
MAX_CHUNKS = 64


async def _embed(texts: list[str]) -> list[list[float]]:
    resp = await get_embedding_client().embeddings.create(model=settings.embedding_model, input=texts)
    return [d.embedding for d in resp.data]


async def _embed_each(texts: list[str]) -> list[list[float]]:
    """One text at a time, halving any text the model rejects as too long. A few 新闻联播 chunks of
    garbled source text tokenize past Ollama's context although they are only ~600 characters."""
    vectors = []
    for text in texts:
        while True:
            try:
                vectors.extend(await _embed([text]))
                break
            except BadRequestError:
                if len(text) <= 64:
                    raise
                text = text[: len(text) // 2]
                print(f"  过长，截成 {len(text)} 字重试")
    return vectors


async def main(recreate: bool, min_chunk: int = 0, skip_existing: bool = False):
    emb = get_embedding_client()
    dim = len((await _embed(["维度探测"]))[0])
    qdrant = get_qdrant()
    if recreate and await qdrant.collection_exists(CHUNK_COLLECTION):
        await qdrant.delete_collection(CHUNK_COLLECTION)
    if not await qdrant.collection_exists(CHUNK_COLLECTION):
        await qdrant.create_collection(CHUNK_COLLECTION, vectors_config=VectorParams(size=dim, distance=Distance.COSINE))
    await ensure_payload_indexes(qdrant, CHUNK_COLLECTION)  # before inserting, so HNSW uses them

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(News.id, News.title, News.content, News.description,
                                        News.author, News.publish_time))).all()
    print(f"父文档 {len(rows)} 条，切 chunk 中…")

    pending_texts: list[str] = []
    pending_points: list[dict] = []   # 暂存 payload+id，embed 后组装
    total_chunks = 0

    async def flush():
        nonlocal total_chunks
        if skip_existing and pending_points:
            existing = {point.id for point in await qdrant.retrieve(
                CHUNK_COLLECTION, ids=[p["id"] for p in pending_points], with_payload=False, with_vectors=False)}
            kept = [(t, p) for t, p in zip(pending_texts, pending_points) if p["id"] not in existing]
            pending_texts[:] = [t for t, _ in kept]
            pending_points[:] = [p for _, p in kept]
        if not pending_texts:
            return
        try:
            vectors = await _embed(pending_texts)
        except BadRequestError:
            vectors = await _embed_each(pending_texts)
        points = [PointStruct(id=p["id"], vector=v, payload=p["payload"])
                  for p, v in zip(pending_points, vectors)]
        await qdrant.upsert(collection_name=CHUNK_COLLECTION, points=points)
        total_chunks += len(points)
        pending_texts.clear()
        pending_points.clear()

    for r in rows:
        body = r.content or r.description or r.title or ""
        chunks = chunk_text(body, size=600, overlap=120, max_chunks=MAX_CHUNKS) or [(r.description or r.title or "")[:600]]
        date_str = r.publish_time.strftime("%Y-%m-%d") if r.publish_time else ""
        ts = int(r.publish_time.timestamp()) if r.publish_time else 0
        for idx, ch in enumerate(chunks):
            if idx < min_chunk:
                continue
            embed_text = f"标题:{r.title}\n日期:{date_str}\n来源:{r.author or ''}\n{ch}"
            pending_texts.append(embed_text)
            pending_points.append({
                "id": int(r.id) * 1000 + idx,
                "payload": {"news_id": int(r.id), "chunk_index": idx, "title": r.title,
                            "source": r.author, "publish_ts": ts, "chunk_text": ch[:800]},
            })
            if len(pending_texts) >= BATCH:
                await flush()
        if total_chunks and total_chunks % (BATCH * 16) < BATCH:
            print(f"  已索引 ~{total_chunks} chunks")
    await flush()

    save_meta(settings.embedding_model, dim)
    await async_engine.dispose()
    print(f"完成：{len(rows)} 父文档 → {total_chunks} 个 chunk 入库（collection={CHUNK_COLLECTION}）")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--recreate", action="store_true")
    parser.add_argument("--min-chunk", type=int, default=0, help="only embed chunks with this index or higher")
    parser.add_argument("--skip-existing", action="store_true", help="do not re-embed chunks already in the collection")
    args = parser.parse_args()
    if args.recreate and args.min_chunk:
        parser.error("--recreate drops the collection; --min-chunk only makes sense without it")
    asyncio.run(main(args.recreate, args.min_chunk, args.skip_existing))
