"""Long-term user memory CRUD (ai_user_memory). The write gate lives in harness/long_term_memory.py."""
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from harness.long_term_memory import MemoryCandidate
from models.ai_agent import AiUserMemory


def to_dict(memory: AiUserMemory) -> dict[str, Any]:
    return {
        "id": memory.id,
        "kind": memory.kind,
        "key": memory.mem_key,
        "value": (memory.value or {}).get("v") if isinstance(memory.value, dict) else memory.value,
        "cue": memory.cue,
        "evidence": memory.evidence or {},
        "hits": memory.hits,
        "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
        "last_used_at": memory.last_used_at.isoformat() if memory.last_used_at else None,
    }


async def list_memories(db: AsyncSession, user_id: int) -> list[AiUserMemory]:
    stmt = select(AiUserMemory).where(AiUserMemory.user_id == user_id).order_by(AiUserMemory.kind, AiUserMemory.id)
    return list((await db.execute(stmt)).scalars().all())


async def remember(db: AsyncSession, user_id: int, candidates: list[MemoryCandidate], *,
                   evidence: dict[str, Any], max_entries: int) -> list[AiUserMemory]:
    """Upsert candidates (same kind+key replaces the value), then evict least recently used beyond the budget."""
    if not candidates:
        return []
    existing = {(m.kind, m.mem_key): m for m in await list_memories(db, user_id)}
    written: list[AiUserMemory] = []
    for candidate in candidates:
        memory = existing.get((candidate.kind, candidate.key))
        if memory is None:
            memory = AiUserMemory(user_id=user_id, kind=candidate.kind, mem_key=candidate.key, hits=0)
            db.add(memory)
        memory.value = {"v": candidate.value}
        memory.cue = candidate.cue
        memory.evidence = evidence
        memory.updated_at = datetime.now()
        written.append(memory)
    await db.flush()
    rows = await list_memories(db, user_id)
    if len(rows) > max_entries:
        rows.sort(key=lambda m: m.last_used_at or m.updated_at or m.created_at)
        stale = [m.id for m in rows[: len(rows) - max_entries] if m not in written]
        if stale:
            await db.execute(delete(AiUserMemory).where(AiUserMemory.id.in_(stale)))
    await db.commit()
    return written


async def touch(db: AsyncSession, memory_ids: list[int]) -> None:
    if not memory_ids:
        return
    await db.execute(
        update(AiUserMemory).where(AiUserMemory.id.in_(memory_ids))
        .values(hits=AiUserMemory.hits + 1, last_used_at=datetime.now())
    )
    await db.commit()


async def delete_memory(db: AsyncSession, user_id: int, memory_id: int) -> bool:
    result = await db.execute(
        delete(AiUserMemory).where(AiUserMemory.id == memory_id, AiUserMemory.user_id == user_id)
    )
    await db.commit()
    return bool(result.rowcount)


async def clear_memories(db: AsyncSession, user_id: int) -> int:
    count = (await db.execute(
        select(func.count()).select_from(AiUserMemory).where(AiUserMemory.user_id == user_id)
    )).scalar_one()
    await db.execute(delete(AiUserMemory).where(AiUserMemory.user_id == user_id))
    await db.commit()
    return int(count)
