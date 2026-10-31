"""Off-site news store: search results kept as an aggregator would keep them.

When the web fallback searches, results from allow-listed news and government sites are saved as
title + snippet + link (never the article text) in the `external_news` table and a separate vector
collection. A later question the station cannot answer looks here before searching the web again,
which saves search quota and makes earlier finds reusable.

The store never feeds the station: rows are not in the `news` table, not in the app feed, and are
cited as [web:<url>] off-site leads, with their own `ext:<id>` ids for provenance. Admission rules:
http(s) URL on an allow-listed domain, a real snippet, nothing that reads like an instruction to the
assistant, and no duplicate URL or duplicate story (same text, or a reprint whose vector is nearly identical). Rows start `unverified`; a reviewer can mark them
`verified` or `rejected` (scripts/review_external_news.py), and rejected rows are never returned.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SUMMARY_MAX_CHARS = 500
# A reprint of one story on another site (gov.cn and a provincial portal, with a different title
# suffix) scored 0.993 against the original; two different State Council meetings scored about 0.6.
DUPLICATE_SCORE = 0.95
MIN_SUMMARY_CHARS = 20
_TRACKING_PARAMS = re.compile(r"^(?:utm_|spm$|from$|wfr$|share|ref$|fr$)", re.IGNORECASE)
_INSTRUCTION_RE = re.compile(
    r"忽略|无视|系统提示|提示词|新指令|assistant\s*[:：]|system\s*[:：]|ignore\s+(?:all|previous|prior|the)"
    r"|untrusted_external_content|(?<![A-Za-z0-9_\-])[A-Za-z]{2,}[-_]\d{3,}(?![A-Za-z0-9_\-])",
    re.IGNORECASE,
)
_SNIPPET_DATE_RE = re.compile(r"^\s*(\d{4})[年\-/.](\d{1,2})[月\-/.](\d{1,2})日?")
# "最近 / 最新 / 今天": a stored snippet may be stale, so these go to the live web first.
_FRESH_RE = re.compile(r"最近|最新|今天|今日|昨天|本周|这周|刚刚|实时|目前|现在")


def wants_fresh(query: str) -> bool:
    return bool(_FRESH_RE.search(query or ""))


def normalize_url(url: str) -> str:
    parts = urlsplit((url or "").strip())
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING_PARAMS.match(k)])
    return urlunsplit((parts.scheme.lower(), (parts.hostname or "").lower() + (f":{parts.port}" if parts.port else ""),
                       parts.path or "/", query, ""))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _story_key(title: str, summary: str) -> str:
    return _sha(re.sub(r"\W+", "", f"{title}{summary[:120]}").lower())


def _domain_allowed(host: str, allowed: tuple[str, ...]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith(f".{d}") for d in (item.lower().lstrip(".") for item in allowed))


def parse_published(item: dict) -> datetime | None:
    raw = str(item.get("published") or "").strip()
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass
    match = _SNIPPET_DATE_RE.match(str(item.get("summary") or ""))
    if match:
        try:
            return datetime(*(int(part) for part in match.groups()))
        except ValueError:
            return None
    return None


@dataclass
class Candidate:
    url: str
    url_hash: str
    content_hash: str
    domain: str
    site: str | None
    title: str
    summary: str
    published_at: datetime | None


def admit(item: dict, allowed_domains: tuple[str, ...]) -> tuple[Candidate | None, str]:
    """(candidate, "") when a search result may be stored, else (None, reason)."""
    url = str(item.get("url") or "")
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None, "bad_url"
    if not _domain_allowed(parts.hostname, allowed_domains):
        return None, "domain"
    title = re.sub(r"\s+", " ", str(item.get("title") or "")).strip()[:255]
    summary = re.sub(r"\s+", " ", str(item.get("summary") or "")).strip()[:SUMMARY_MAX_CHARS]
    if not title or len(summary) < MIN_SUMMARY_CHARS:
        return None, "thin"
    if _INSTRUCTION_RE.search(f"{title} {summary}"):
        return None, "instruction"
    normalized = normalize_url(url)
    return Candidate(
        url=normalized,
        url_hash=_sha(normalized),
        content_hash=_story_key(title, summary),
        domain=parts.hostname.lower(),
        site=(str(item.get("site")).strip()[:128] or None) if item.get("site") else None,
        title=title,
        summary=summary,
        published_at=parse_published(item),
    ), ""


class Repository(Protocol):
    async def existing(self, url_hashes: list[str], content_hashes: list[str]) -> dict[str, int]: ...
    async def insert(self, candidate: Candidate, *, query: str, backend: str) -> int: ...
    async def touch(self, ids: list[int]) -> None: ...
    async def rows(self, ids: list[int]) -> list[dict[str, Any]]: ...


class VectorIndex(Protocol):
    async def upsert(self, ext_id: int, text: str, payload: dict[str, Any]) -> None: ...
    async def query(self, text: str, limit: int) -> list[tuple[int, float]]: ...


class ExternalNewsStore:
    def __init__(self, repo: Repository, index: VectorIndex, *, allowed_domains: tuple[str, ...], min_score: float):
        self.repo = repo
        self.index = index
        self.allowed_domains = allowed_domains
        self.min_score = min_score

    async def ingest(self, items: list[dict], *, query: str, backend: str) -> dict[str, Any]:
        """Store admissible results; returns counts of new, already-known and rejected-by-reason."""
        stats: dict[str, Any] = {"new": 0, "seen": 0, "rejected": {}}
        candidates: list[Candidate] = []
        for item in items:
            candidate, reason = admit(item, self.allowed_domains)
            if candidate is None:
                stats["rejected"][reason] = stats["rejected"].get(reason, 0) + 1
            elif all(c.url_hash != candidate.url_hash and c.content_hash != candidate.content_hash for c in candidates):
                candidates.append(candidate)
        if not candidates:
            return stats
        known = await self.repo.existing([c.url_hash for c in candidates], [c.content_hash for c in candidates])
        seen_ids: list[int] = []
        for candidate in candidates:
            ext_id = known.get(candidate.url_hash) or known.get(candidate.content_hash)
            if not ext_id:
                nearest = await self.index.query(f"{candidate.title}\n{candidate.summary}", 1)
                if nearest and nearest[0][1] >= DUPLICATE_SCORE:
                    ext_id = nearest[0][0]
            if ext_id:
                seen_ids.append(ext_id)
                continue
            ext_id = await self.repo.insert(candidate, query=query[:255], backend=backend[:32])
            await self.index.upsert(ext_id, f"{candidate.title}\n{candidate.summary}", {
                "ext_id": ext_id, "url": candidate.url, "domain": candidate.domain,
                "published_ts": int(candidate.published_at.timestamp()) if candidate.published_at else None,
            })
            stats["new"] += 1
        if seen_ids:
            await self.repo.touch(sorted(set(seen_ids)))
            stats["seen"] = len(set(seen_ids))
        return stats

    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Stored leads close enough to the question, shaped like web_search items."""
        hits = [(ext_id, score) for ext_id, score in await self.index.query(query, limit * 2) if score >= self.min_score]
        if not hits:
            return []
        scores = dict(hits)
        rows = [row for row in await self.repo.rows([ext_id for ext_id, _ in hits]) if row.get("status") != "rejected"]
        rows.sort(key=lambda row: scores.get(row["id"], 0), reverse=True)
        return [
            {
                "title": row["title"],
                "url": row["url"],
                "summary": row["summary"],
                "site": row.get("site"),
                "published": row["published_at"].isoformat() if row.get("published_at") else None,
                "ext_id": f"ext:{row['id']}",
                "status": row.get("status"),
                "score": round(scores.get(row["id"], 0.0), 4),
            }
            for row in rows[:limit]
        ]


# ---- real backends: MariaDB table + Qdrant collection -------------------------------------------

class SqlRepository:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def existing(self, url_hashes: list[str], content_hashes: list[str]) -> dict[str, int]:
        from sqlalchemy import or_, select

        from models.external_news import ExternalNews

        async with self.session_factory() as db:
            result = await db.execute(
                select(ExternalNews.id, ExternalNews.url_hash, ExternalNews.content_hash).where(
                    or_(ExternalNews.url_hash.in_(url_hashes), ExternalNews.content_hash.in_(content_hashes))
                )
            )
            found: dict[str, int] = {}
            for ext_id, url_hash, content_hash in result.all():
                found.setdefault(url_hash, ext_id)
                found.setdefault(content_hash, ext_id)
            return found

    async def insert(self, candidate: Candidate, *, query: str, backend: str) -> int:
        from models.external_news import ExternalNews

        async with self.session_factory() as db:
            row = ExternalNews(
                url=candidate.url, url_hash=candidate.url_hash, content_hash=candidate.content_hash,
                domain=candidate.domain, site=candidate.site, title=candidate.title, summary=candidate.summary,
                published_at=candidate.published_at, first_query=query, backend=backend,
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            return row.id

    async def touch(self, ids: list[int]) -> None:
        from sqlalchemy import update

        from models.external_news import ExternalNews

        async with self.session_factory() as db:
            await db.execute(
                update(ExternalNews).where(ExternalNews.id.in_(ids))
                .values(hits=ExternalNews.hits + 1, last_seen_at=datetime.now())
            )
            await db.commit()

    async def rows(self, ids: list[int]) -> list[dict[str, Any]]:
        from sqlalchemy import select

        from models.external_news import ExternalNews

        async with self.session_factory() as db:
            result = await db.execute(select(ExternalNews).where(ExternalNews.id.in_(ids)))
            return [
                {key: getattr(row, key) for key in ("id", "url", "title", "summary", "site", "published_at", "status")}
                for row in result.scalars().all()
            ]


class QdrantIndex:
    def __init__(self, client, collection: str, embed):
        self.client = client
        self.collection = collection
        self.embed = embed

    async def _ensure(self, dim: int) -> None:
        from qdrant_client.models import Distance, VectorParams

        if not await self.client.collection_exists(self.collection):
            await self.client.create_collection(
                collection_name=self.collection, vectors_config=VectorParams(size=dim, distance=Distance.COSINE)
            )

    async def upsert(self, ext_id: int, text: str, payload: dict[str, Any]) -> None:
        from qdrant_client.models import PointStruct

        vector = (await self.embed([text]))[0]
        await self._ensure(len(vector))
        await self.client.upsert(collection_name=self.collection, points=[PointStruct(id=ext_id, vector=vector, payload=payload)])

    async def query(self, text: str, limit: int) -> list[tuple[int, float]]:
        if not await self.client.collection_exists(self.collection):
            return []
        vector = (await self.embed([text]))[0]
        result = await self.client.query_points(collection_name=self.collection, query=vector, limit=limit)
        return [(int(point.id), float(point.score)) for point in result.points]


def default_store() -> ExternalNewsStore:
    from config.ai_conf import settings
    from config.db_conf import AsyncSessionLocal
    from config.vector_conf import get_qdrant
    from harness.rag_index import _embed

    return ExternalNewsStore(
        SqlRepository(AsyncSessionLocal),
        QdrantIndex(get_qdrant(), settings.external_news_collection, _embed),
        allowed_domains=tuple(settings.external_news_allowed_domains),
        min_score=settings.external_news_min_score,
    )
