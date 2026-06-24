"""Compatibility entrypoint for rebuilding the unified news RAG index.

The Claude base already owns the runnable parent-child chunk index builder in
scripts.build_chunk_index. This wrapper keeps the Codex merge contract stable
without creating a second indexing path.
"""

from __future__ import annotations

import argparse
import asyncio

from scripts.build_chunk_index import main as build_chunk_index


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recreate", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(build_chunk_index(args.recreate))
