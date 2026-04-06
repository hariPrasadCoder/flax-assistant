from __future__ import annotations

"""
Memory layer — reads and writes time-stamped memories.

Short-term: conversations, events (last 48h)
Long-term: learnings, patterns (permanent until compressed/updated)
"""

from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from ..models import Memory, MemoryType
import uuid


async def save_memory(
    db: AsyncSession,
    content: str,
    memory_type: MemoryType,
    user_id: str | None = None,
    team_id: str | None = None,
    task_id: str | None = None,
    importance: float = 0.5,
    ttl_hours: int | None = 48,  # None = permanent
) -> Memory:
    """Save a memory with optional TTL."""
    expires_at = None
    if ttl_hours:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)

    memory = Memory(
        id=str(uuid.uuid4()),
        user_id=user_id,
        team_id=team_id,
        type=memory_type,
        content=content,
        importance=importance,
        expires_at=expires_at,
        task_id=task_id,
    )
    db.add(memory)
    await db.flush()
    return memory


async def get_recent_memories(
    db: AsyncSession,
    user_id: str,
    hours: int = 48,
    memory_types: list[MemoryType] | None = None,
) -> list[dict]:
    """Get recent non-expired memories for a user."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    now = datetime.now(timezone.utc)

    conditions = [
        Memory.user_id == user_id,
        Memory.created_at >= since,
        Memory.compressed == False,
        (Memory.expires_at == None) | (Memory.expires_at > now),
    ]

    if memory_types:
        conditions.append(Memory.type.in_(memory_types))

    result = await db.execute(
        select(Memory)
        .where(and_(*conditions))
        .order_by(Memory.created_at.desc())
        .limit(20)
    )
    memories = result.scalars().all()

    return [
        {
            "id": m.id,
            "type": m.type.value,
            "content": m.content,
            "created_at": m.created_at.isoformat(),
            "importance": m.importance,
        }
        for m in reversed(memories)
    ]


async def get_learnings(
    db: AsyncSession,
    user_id: str,
) -> list[dict]:
    """Get long-term learnings (permanent memories) for a user."""
    result = await db.execute(
        select(Memory)
        .where(
            Memory.user_id == user_id,
            Memory.type == MemoryType.learning,
            Memory.compressed == False,
        )
        .order_by(Memory.importance.desc())
        .limit(10)
    )
    learnings = result.scalars().all()
    return [{"id": m.id, "content": m.content} for m in learnings]


async def upsert_learning(
    db: AsyncSession,
    user_id: str,
    content: str,
    importance: float = 0.7,
) -> None:
    """Save a new learning about the user (permanent, high importance)."""
    await save_memory(
        db=db,
        content=content,
        memory_type=MemoryType.learning,
        user_id=user_id,
        importance=importance,
        ttl_hours=None,  # permanent
    )
