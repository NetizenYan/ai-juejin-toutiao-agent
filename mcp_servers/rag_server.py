"""RAG MCP server（FastMCP）——语义检索站内新闻（向量召回）。

retrieve_news：query → embedding → Qdrant 向量检索 → 返回最相关新闻 + 证据编号。
相比关键词 LIKE：① 毫秒级（向量索引）；② 语义匹配（"AI芯片"≈"算力/英伟达"）。
返回 evidence-pack 结构（含 doc/score），模型据此引用 [news:ID]。

启动（stdio）：<agent-python> -m mcp_servers.rag_server
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from config.ai_conf import settings, get_embedding_client
from config.vector_conf import get_qdrant, assert_meta_matches, CHUNK_COLLECTION
from harness.rag_search import search_news_rag
from harness.rag_search_v2 import search_news_rag_v2

mcp = FastMCP("toutiao-rag")


@mcp.tool()
async def retrieve_news(
    query: str,
    limit: int = 50,
    carryover_evidence_ids: list[str] | None = None,
) -> dict:
    """语义检索站内新闻（父子索引）：在 chunk 子级向量召回，返回 chunk 候选。

    返回的是 chunk 级候选（含 news_id / chunk_text / publish_ts），由 harness 做
    cross-encoder 精排 + 聚合到 parent news_id + 时间衰减 + 去重。
    """
    if settings.rag_search_version == "v2":
        return await search_news_rag_v2(
            query,
            limit=limit,
            tool_name="retrieve_news",
            embedding_client_factory=get_embedding_client,
            qdrant_factory=get_qdrant,
            carryover_evidence_ids=carryover_evidence_ids or [],
        )

    return await search_news_rag(
        query,
        limit=limit,
        tool_name="retrieve_news",
        embedding_client_factory=get_embedding_client,
        qdrant_factory=get_qdrant,
        assert_meta_matches_fn=assert_meta_matches,
    )


if __name__ == "__main__":
    mcp.run()
