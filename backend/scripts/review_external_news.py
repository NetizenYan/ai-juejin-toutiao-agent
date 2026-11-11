"""Review the off-site news store (external_news).

    python -m backend.scripts.review_external_news stats
    python -m backend.scripts.review_external_news list [--status unverified] [--limit 20]
    python -m backend.scripts.review_external_news verify 12 15 --note "与新华社原文一致"
    python -m backend.scripts.review_external_news reject 13 --note "转载站，内容走样"

Rejected rows stay in the table (so the same page is not stored again) but are never returned to
the assistant. Verified only records that a person checked the page; answers still label every
off-site lead as such.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime

from sqlalchemy import func, select, update

from backend.app.db.session import AsyncSessionLocal
from backend.app.models.external_news import ExternalNews

STATUSES = ("unverified", "verified", "rejected")


async def _stats() -> None:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(ExternalNews.status, func.count()).group_by(ExternalNews.status))).all()
        domains = (await db.execute(
            select(ExternalNews.domain, func.count()).group_by(ExternalNews.domain).order_by(func.count().desc()).limit(10)
        )).all()
    print("by status:", {status: count for status, count in rows} or "empty")
    for domain, count in domains:
        print(f"  {count:5d}  {domain}")


async def _list(status: str | None, limit: int) -> None:
    query = select(ExternalNews).order_by(ExternalNews.id.desc()).limit(limit)
    if status:
        query = query.where(ExternalNews.status == status)
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(query)).scalars().all()
    for row in rows:
        published = row.published_at.date().isoformat() if row.published_at else "日期未知"
        print(f"ext:{row.id}  [{row.status}] {published}  {row.site or row.domain}  hits={row.hits}")
        print(f"    {row.title}")
        print(f"    {row.summary[:120]}")
        print(f"    {row.url}")


async def _set_status(ids: list[int], status: str, note: str) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(ExternalNews).where(ExternalNews.id.in_(ids))
            .values(status=status, review_note=note or None, reviewed_at=datetime.now())
        )
        await db.commit()
    print(f"{result.rowcount} row(s) -> {status}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("stats")
    listing = sub.add_parser("list")
    listing.add_argument("--status", choices=STATUSES)
    listing.add_argument("--limit", type=int, default=20)
    for name in ("verify", "reject"):
        action = sub.add_parser(name)
        action.add_argument("ids", type=int, nargs="+")
        action.add_argument("--note", default="")
    args = parser.parse_args()

    if args.command == "stats":
        asyncio.run(_stats())
    elif args.command == "list":
        asyncio.run(_list(args.status, args.limit))
    else:
        asyncio.run(_set_status(args.ids, "verified" if args.command == "verify" else "rejected", args.note))


if __name__ == "__main__":
    main()
