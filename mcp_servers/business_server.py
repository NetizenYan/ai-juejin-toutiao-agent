"""业务 MCP server（FastMCP）——把站内业务能力暴露为受控工具。

铁律：
- 只暴露**业务工具**，绝不暴露 SQL / 通用查询代理；
- 内部复用现有 crud，模型/harness 只看到最小化投影（不返回全文 dump、不暴露 ORM、无 DB 凭据）；
- 作为跨语言稳定契约：将来 harness 换 Node/eve 时本 server 原样复用。

启动（stdio）：
    <agent-python> -m mcp_servers.business_server
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from config.db_conf import AsyncSessionLocal, async_engine
from crud import news as news_crud
from crud import history as history_crud

mcp = FastMCP("toutiao-business")


# ---------- 投影：把 ORM 对象压成模型可见的最小字段 ----------
def _dt(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    return str(value) if value else None


def _clip(text: Optional[str], limit: int) -> str:
    value = (text or "").strip()
    return value if len(value) <= limit else value[:limit].rstrip() + "..."


def _list_item(item: Any) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "summary": _clip(item.description or item.content, 220),
        "author": item.author,
        "publish_time": _dt(item.publish_time),
        "views": item.views,
    }


def _detail(item: Any) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "summary": _clip(item.description or item.content, 260),
        "content_excerpt": _clip(item.content, 1200),
        "author": item.author,
        "publish_time": _dt(item.publish_time),
        "views": item.views,
        "image_url": item.image,
    }


# ---------- 工具 ----------
@mcp.tool()
async def news_search(query: str, limit: int = 5) -> dict:
    """按关键词搜索站内新闻，返回标题+摘要+证据编号（不返回全文，不暴露 SQL）。"""
    limit = max(1, min(int(limit), 20))
    try:
        async with AsyncSessionLocal() as db:
            rows = await news_crud.search_news(db, query, limit=limit)
    finally:
        await async_engine.dispose()
    return {
        "tool": "news_search",
        "items": [_list_item(r) for r in rows],
        "evidence_ids": [f"news:{r.id}" for r in rows],
    }


@mcp.tool()
async def news_detail(news_id: int) -> dict:
    """获取单条站内新闻的详情摘录 + 证据编号。"""
    try:
        async with AsyncSessionLocal() as db:
            row = await news_crud.get_news_detail(db, int(news_id))
    finally:
        await async_engine.dispose()
    if not row:
        return {"tool": "news_detail", "item": None, "evidence_ids": []}
    return {"tool": "news_detail", "item": _detail(row), "evidence_ids": [f"news:{row.id}"]}


@mcp.tool()
async def user_recent_history(user_id: int, limit: int = 5) -> dict:
    """获取某用户最近浏览过的新闻（仅 news_qa / recommendation 意图可用；权限在 harness 控制）。"""
    limit = max(1, min(int(limit), 20))
    try:
        async with AsyncSessionLocal() as db:
            rows, _total = await history_crud.get_history_list(db, int(user_id), page=1, page_size=limit)
    finally:
        await async_engine.dispose()
    items = [_list_item(news) for (news, _view_time, _hid) in rows]
    return {
        "tool": "user_recent_history",
        "items": items,
        "evidence_ids": [f"news:{it['id']}" for it in items],
    }


@mcp.tool()
async def recommend_news(user_id: int, limit: int = 5) -> dict:
    """推荐新闻候选（MVP 规则版：按热门+最新排序）。无主题的"推荐/看看"类请求用它，不要用关键词搜。user_id 由 harness 注入。"""
    limit = max(1, min(int(limit), 10))
    try:
        async with AsyncSessionLocal() as db:
            rows = await news_crud.recommend_news(db, limit=limit)
    finally:
        await async_engine.dispose()
    items = [_list_item(r) for r in rows]
    return {
        "tool": "recommend_news",
        "items": items,
        "evidence_ids": [f"news:{it['id']}" for it in items],
    }


if __name__ == "__main__":
    mcp.run()  # 默认 stdio 传输
