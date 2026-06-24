"""新闻联播数据集（TXT，2006-2025）入库脚本。

每个 txt = 一天的新闻联播文字稿 → 入库为一条 News（粒度：一篇/天）。
- title:   新闻联播 YYYY-MM-DD｜<首句摘要>
- content: 全文（截断到 60000 字以适配 TEXT 列）
- author:  新闻联播（同时作为可回滚标记）
- publish_time: 文件名日期 19:00
- 分类:    默认「头条」（新闻联播无分类元数据）

幂等：先删除 author='新闻联播' 的旧行再批量插入。

用法（项目根目录）：
    <agent-python> -m scripts.ingest_cctv --root "D:\\Files\\BaiDu\\006-新闻联播数据"
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
from datetime import datetime

from sqlalchemy import select, delete

from config.db_conf import AsyncSessionLocal, async_engine
from models.news import News, Category

AUTHOR_TAG = "新闻联播"
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
CONTENT_CAP = 20000  # TEXT 上限 65535 字节，中文 utf8mb4≈3字节/字 → 限 ~20000 字保险


def _iter_txt(root: str):
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if fn.lower().endswith(".txt"):
                yield os.path.join(dirpath, fn)


def _date_from_name(path: str) -> datetime:
    m = DATE_RE.search(os.path.basename(path))
    if not m:
        return datetime.now()
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), 19, 0, 0)
    except ValueError:
        return datetime.now()


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read().strip()


async def main(root: str):
    files = sorted(_iter_txt(root))
    print(f"发现 {len(files)} 个 txt")

    async with AsyncSessionLocal() as db:
        cat_id = ((await db.execute(select(Category).where(Category.name == "头条"))).scalar_one_or_none())
        category_id = cat_id.id if cat_id else 1

        # 幂等：清掉旧的新闻联播数据
        removed = (await db.execute(delete(News).where(News.author == AUTHOR_TAG))).rowcount
        await db.commit()
        print(f"清理旧的新闻联播行：{removed}")

        batch = []
        inserted = 0
        for i, path in enumerate(files, 1):
            text = _read(path)
            if not text:
                continue
            dt = _date_from_name(path)
            first = text.replace("\n", " ")[:24]
            title = f"新闻联播 {dt.strftime('%Y-%m-%d')}｜{first}"
            batch.append(News(
                title=title[:255],
                description=text.replace("\n", " ")[:500],
                content=text[:CONTENT_CAP],
                image=None,
                author=AUTHOR_TAG,
                category_id=category_id,
                views=0,
                publish_time=dt,
            ))
            if len(batch) >= 500:
                db.add_all(batch)
                await db.commit()
                inserted += len(batch)
                batch = []
                print(f"  已入库 {inserted}/{len(files)}")
        if batch:
            db.add_all(batch)
            await db.commit()
            inserted += len(batch)
    await async_engine.dispose()
    print(f"完成：新入库 {inserted} 条新闻联播")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=r"D:\Files\BaiDu\006-新闻联播数据")
    args = parser.parse_args()
    asyncio.run(main(args.root))
