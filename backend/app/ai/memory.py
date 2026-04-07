from __future__ import annotations

"""
Memory layer — reads and writes time-stamped memories.

Short-term: conversations, events (last 48h)
Long-term: learnings, patterns (permanent until compressed/updated)
"""

from datetime import datetime, timezone, timedelta
from supabase import AsyncClient
from ..models import MemoryType
import uuid


async def save_memory(
    db: AsyncClient,
    content: str,
    memory_type: MemoryType,
    user_id: str | None = None,
    team_id: str | None = None,
    task_id: str | None = None,
    importance: float = 0.5,
    ttl_hours: int | None = 48,  # None = permanent
) -> dict:
    """Save a memory with optional TTL."""
    expires_at = None
    if ttl_hours:
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat()

    memory_dict = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "team_id": team_id,
        "type": memory_type.value if isinstance(memory_type, MemoryType) else memory_type,
        "content": content,
        "importance": importance,
        "expires_at": expires_at,
        "task_id": task_id,
        "compressed": False,
    }
    res = await db.table("memories").insert(memory_dict).execute()
    return res.data[0] if res.data else memory_dict


async def get_recent_memories(
    db: AsyncClient,
    user_id: str,
    hours: int = 48,
    memory_types: list[MemoryType] | None = None,
) -> list[dict]:
    """Get recent non-expired memories for a user."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()

    query = (
        db.table("memories")
        .select("*")
        .eq("user_id", user_id)
        .gt("created_at", since)
        .eq("compressed", False)
        .or_(f"expires_at.is.null,expires_at.gt.{now_iso}")
        .order("created_at", desc=True)
        .limit(20)
    )

    if memory_types:
        type_values = [
            mt.value if isinstance(mt, MemoryType) else mt for mt in memory_types
        ]
        # Filter by type using in_ — PostgREST supports comma-separated list
        query = query.in_("type", type_values)

    res = await query.execute()
    memories = res.data or []

    return [
        {
            "id": m["id"],
            "type": m["type"],
            "content": m["content"],
            "created_at": m["created_at"],
            "importance": m["importance"],
        }
        for m in reversed(memories)
    ]


async def get_learnings(
    db: AsyncClient,
    user_id: str,
) -> list[dict]:
    """Get long-term learnings (permanent memories) for a user."""
    res = await (
        db.table("memories")
        .select("*")
        .eq("user_id", user_id)
        .eq("type", MemoryType.learning.value)
        .eq("compressed", False)
        .order("importance", desc=True)
        .limit(10)
        .execute()
    )
    learnings = res.data or []
    return [{"id": m["id"], "content": m["content"]} for m in learnings]


def _word_overlap(a: str, b: str) -> float:
    """Jaccard similarity on word sets — quick near-duplicate check."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


async def upsert_learning(
    db: AsyncClient,
    user_id: str,
    content: str,
    importance: float = 0.7,
) -> None:
    """Save a learning about the user — skips insert if a similar one already exists."""
    res = await (
        db.table("memories")
        .select("*")
        .eq("user_id", user_id)
        .eq("type", MemoryType.learning.value)
        .eq("compressed", False)
        .execute()
    )
    existing = res.data or []

    # If any existing learning is >60% similar, bump its importance and stop
    for m in existing:
        if _word_overlap(content, m["content"]) > 0.6:
            new_importance = max(m["importance"], importance)
            await db.table("memories").update({"importance": new_importance}).eq("id", m["id"]).execute()
            return

    await save_memory(
        db=db,
        content=content,
        memory_type=MemoryType.learning,
        user_id=user_id,
        importance=importance,
        ttl_hours=None,  # permanent
    )
