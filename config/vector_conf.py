"""向量库（Qdrant）配置 + collection 锁定。

- 复用本机已运行的 Qdrant（localhost:6333）；用独立 collection，不碰他人 `news_chunks`。
- 维度不写死：建索引时按 embedding 实际维度建 collection 并写入 config/rag_meta.json；
  rag server 启动/查询时校验「当前 embedding 模型 + 维度」与 collection 元数据一致，不一致拒绝。
"""
from __future__ import annotations

import json
import os

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION = os.getenv("RAG_COLLECTION_NAME") or os.getenv("RAG_COLLECTION", "toutiao_news_claude")  # 父级
CHUNK_COLLECTION = os.getenv("RAG_CHUNK_COLLECTION_NAME") or os.getenv(
    "RAG_CHUNK_COLLECTION", "toutiao_chunks_claude"
)  # 子级（段落 chunk，父子索引）
_META_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "rag_meta.json")


def get_qdrant() -> AsyncQdrantClient:
    return AsyncQdrantClient(url=QDRANT_URL)


def save_meta(model: str, dim: int) -> None:
    with open(_META_PATH, "w", encoding="utf-8") as f:
        json.dump({"collection": COLLECTION, "embedding_model": model, "vector_dim": dim}, f, ensure_ascii=False)


def load_meta() -> dict | None:
    if not os.path.exists(_META_PATH):
        return None
    with open(_META_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def assert_meta_matches(model: str, dim: int) -> None:
    """启动/查询前校验：当前 embedding 配置必须与建索引时一致，否则向量空间不可比。"""
    meta = load_meta()
    if not meta:
        raise RuntimeError("RAG 未建索引（缺 config/rag_meta.json），请先运行 scripts.build_news_index")
    if meta.get("embedding_model") != model or int(meta.get("vector_dim", 0)) != int(dim):
        raise RuntimeError(
            f"RAG 配置不一致：collection 用 {meta.get('embedding_model')}/{meta.get('vector_dim')}，"
            f"当前 {model}/{dim}。请重建索引或改回原 embedding 模型。"
        )


async def ensure_collection(client: AsyncQdrantClient, dim: int, recreate: bool = False) -> None:
    exists = await client.collection_exists(COLLECTION)
    if exists and recreate:
        await client.delete_collection(COLLECTION)
        exists = False
    if not exists:
        await client.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
