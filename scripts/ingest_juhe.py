"""聚合数据「AI新闻简报列表」入库脚本。

把外部新闻沉淀进站内 news 表，之后 MCP 业务工具(news_search/recommend_news)即可直接用，
不必每次查询都消耗 juhe 配额（50/天）。一次运行 = 1 次调用（约 10 条）。

用法（项目根目录）：
    <agent-python> -m scripts.ingest_juhe            # 全部类型
    <agent-python> -m scripts.ingest_juhe --type tech
"""
from __future__ import annotations

import argparse
import asyncio
import urllib.parse
import urllib.request
import json
from datetime import datetime

from sqlalchemy import select

from config.ai_conf import settings
from config.db_conf import AsyncSessionLocal, async_engine
from models.news import News, Category
from harness.rag_index import upsert_news_rows

API_URL = "https://apis.juhe.cn/fapigw/aibrief/list"

# juhe type → 站内分类名（命中则用，否则默认“头条”）
_TYPE_TO_CATEGORY = {
    "tech": "科技", "keji": "科技", "ai": "科技", "digital": "科技", "game": "科技", "internet": "科技",
    "finance": "财经", "caijing": "财经", "money": "财经", "stock": "财经",
    "sports": "体育", "tiyu": "体育",
    "ent": "娱乐", "yule": "娱乐", "star": "娱乐",
    "world": "国际", "guoji": "国际",
    "china": "国内", "guonei": "国内",
    "society": "社会", "shehui": "社会",
}


def _fetch(news_type: str, page: int = 1, page_size: int = 10) -> list[dict]:
    params = {"key": settings.juhe_api_key, "type": news_type, "page": page, "page_size": page_size}
    url = API_URL + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    code = data.get("error_code")
    if code != 0:
        # 配额耗尽（10012/10013）等：抛出，由上层优雅终止（不视为崩溃）
        raise RuntimeError(f"juhe error {code}: {data.get('reason')}")
    return (data.get("result") or {}).get("list") or []


def _fetch_many(news_type: str, target: int, max_pages: int = 8) -> list[dict]:
    """分页拉取，按 url/title 去重，最多取 target 条（每页约 10 条 = 1 次调用）。"""
    collected: list[dict] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        if len(collected) >= target:
            break
        try:
            items = _fetch(news_type, page=page, page_size=10)
        except RuntimeError as exc:
            # 配额耗尽/接口报错：优雅停止（已拿到的照常入库），不让定时任务崩溃
            print(f"  page {page}: 停止拉取（{exc}）")
            break
        print(f"  page {page}: 返回 {len(items)} 条")
        if not items:
            break
        new_in_page = 0
        for it in items:
            ukey = it.get("url") or it.get("id") or it.get("title")
            if ukey in seen:
                continue
            seen.add(ukey)
            collected.append(it)
            new_in_page += 1
        if new_in_page == 0:  # 整页都是重复 → 没有更多新数据
            break
    return collected[:target]


def _parse_dt(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return datetime.now()


async def main(news_type: str, target: int = 50):
    items = _fetch_many(news_type, target=target)
    print(f"共拉取 {len(items)} 条（type={news_type or 'all'}, 目标 {target}）")

    async with AsyncSessionLocal() as db:
        # 分类名 → id
        cats = (await db.execute(select(Category))).scalars().all()
        name_to_id = {c.name: c.id for c in cats}
        default_cat = name_to_id.get("头条") or (cats[0].id if cats else 1)

        new_rows = []
        for it in items:
            title = (it.get("title") or "").strip()
            if not title:
                continue
            # 按标题去重
            exists = await db.execute(select(News.id).where(News.title == title))
            if exists.scalar_one_or_none():
                continue

            summary = (it.get("summary") or title).strip()
            url = it.get("url") or ""
            author = (it.get("author_name") or "聚合AI简报")[:50]
            cat_name = _TYPE_TO_CATEGORY.get((it.get("type") or "").lower(), "头条")
            category_id = name_to_id.get(cat_name, default_cat)
            content = summary + (f"\n\n原文链接：{url}" if url else "") + "\n（来源：聚合数据 AI 新闻简报）"

            row = News(
                title=title[:255], description=summary[:500], content=content,
                image=(it.get("image_url") or None), author=author,
                category_id=category_id, views=0, publish_time=_parse_dt(it.get("publish_date")),
            )
            db.add(row)
            new_rows.append(row)

        await db.commit()
        # 刷新拿到自增 id，供增量 embed
        index_rows = [(r.id, r.title, r.description) for r in new_rows]

    # 步骤③：增量 embed —— 只对本次新增的行写入 Qdrant（不重建）
    indexed = await upsert_news_rows(index_rows)
    await async_engine.dispose()
    print(f"新入库 {len(index_rows)} 条（已去重），增量 embed {indexed} 条")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", default="", help="juhe 新闻类型，默认空=全部")
    parser.add_argument("--target", type=int, default=50, help="目标拉取条数（每页约10条/次调用）")
    args = parser.parse_args()
    asyncio.run(main(args.type, args.target))
