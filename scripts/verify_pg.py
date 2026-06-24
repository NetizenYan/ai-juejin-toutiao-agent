"""Verify the isolated PostgreSQL v2 store."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import asyncpg

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.rebuild_pipeline import pg_config_from_env  # noqa: E402


async def verify(args: argparse.Namespace) -> dict:
    conn = await asyncpg.connect(**pg_config_from_env(args))
    try:
        row = await conn.fetchrow(
            """
            SELECT
              to_regclass('public.news_unified') IS NOT NULL AS has_news_unified,
              to_regclass('public.news_chunks_meta') IS NOT NULL AS has_news_chunks_meta
            """
        )
        counts = {"parents": None, "chunks": None}
        if row["has_news_unified"] and row["has_news_chunks_meta"]:
            count_row = await conn.fetchrow(
                "SELECT (SELECT count(*) FROM news_unified) AS parents, "
                "(SELECT count(*) FROM news_chunks_meta) AS chunks"
            )
            counts = {"parents": int(count_row["parents"]), "chunks": int(count_row["chunks"])}
        return {
            "ok": bool(row["has_news_unified"] and row["has_news_chunks_meta"]),
            "tables": dict(row),
            "counts": counts,
            "database": args.pg_database,
            "host": args.pg_host,
            "port": args.pg_port,
        }
    finally:
        await conn.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify isolated PostgreSQL v2 tables.")
    parser.add_argument("--pg-host", default="127.0.0.1")
    parser.add_argument("--pg-port", type=int, default=5433)
    parser.add_argument("--pg-user", default="postgres")
    parser.add_argument("--pg-password", default="postgres")
    parser.add_argument("--pg-database", default="toutiao_agent")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    if sys.platform == "win32" and sys.version_info < (3, 14):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    print(json.dumps(asyncio.run(verify(parse_args(argv))), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
