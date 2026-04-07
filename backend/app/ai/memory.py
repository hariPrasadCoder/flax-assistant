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
    """Save a learning — uses Jaccard fast-pass then LLM semantic dedup."""
    import logging
    logger = logging.getLogger(__name__)

    res = await (
        db.table("memories")
        .select("id, content, importance")
        .eq("user_id", user_id)
        .eq("type", MemoryType.learning.value)
        .eq("compressed", False)
        .execute()
    )
    existing = res.data or []

    if existing:
        # Fast Jaccard pass — catches near-exact duplicates cheaply
        for m in existing:
            if _word_overlap(content, m["content"]) > 0.6:
                new_importance = max(m["importance"], importance)
                await db.table("memories").update({"importance": new_importance}).eq("id", m["id"]).execute()
                return

        # Semantic LLM pass — catches paraphrase/synonym duplicates Jaccard misses
        try:
            from .llm import llm_complete
            from ..config import settings
            if settings.gemini_api_key:
                existing_text = "\n".join(f"- {m['content']}" for m in existing[:10])
                raw = await llm_complete(
                    system="You are a deduplication assistant. Answer only 'yes' or 'no'.",
                    messages=[{"role": "user", "content": (
                        f"Existing learnings about this user:\n{existing_text}\n\n"
                        f"New insight: \"{content}\"\n\n"
                        "Is this new insight already captured (same meaning) by any existing learning?"
                    )}],
                    model="gemini/gemini-2.5-flash",
                    temperature=0.0,
                    max_tokens=5,
                )
                if raw.strip().lower().startswith("yes"):
                    # Bump importance on the most word-similar existing learning
                    best = max(existing, key=lambda m: _word_overlap(content, m["content"]))
                    await db.table("memories").update(
                        {"importance": max(best["importance"], importance)}
                    ).eq("id", best["id"]).execute()
                    return
        except Exception as e:
            logger.debug("LLM dedup check failed, inserting anyway: %s", e)

    await save_memory(
        db=db,
        content=content,
        memory_type=MemoryType.learning,
        user_id=user_id,
        importance=importance,
        ttl_hours=None,  # permanent
    )


async def compress_and_learn(db: AsyncClient, user_id: str) -> int:
    """
    Summarize recent short-term memories into durable learnings via LLM.
    Marks compressed memories so they stop appearing in context.
    Returns the number of memories compressed.
    """
    import json
    import logging
    logger = logging.getLogger(__name__)

    compress_since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    old_res = await (
        db.table("memories")
        .select("*")
        .eq("user_id", user_id)
        .eq("compressed", False)
        .neq("type", MemoryType.learning.value)
        .lt("created_at", compress_since)
        .limit(20)
        .execute()
    )
    memories = old_res.data or []
    if not memories:
        return 0

    content_block = "\n".join(f"- {m['content']}" for m in memories)

    try:
        from .llm import llm_complete
        from ..config import settings
        if settings.gemini_api_key:
            raw = await llm_complete(
                system="You extract behavioral insights from activity logs. Be specific and concise.",
                messages=[{"role": "user", "content": (
                    f"Recent activity for this user:\n{content_block}\n\n"
                    "Extract 1-3 specific, durable insights about this user's behavior, "
                    "work patterns, or preferences. Only include insights actually evidenced "
                    "by this data. Skip generic observations.\n\n"
                    'Return a JSON array of strings, e.g. ["User completes tasks faster when deadlines are self-set"]\n'
                    "Return only the JSON array."
                )}],
                model="gemini/gemini-2.5-flash",
                temperature=0.3,
                max_tokens=300,
            )
            insights = json.loads(raw.strip())
            if isinstance(insights, list):
                for insight in insights[:3]:
                    if isinstance(insight, str) and insight.strip():
                        await upsert_learning(db, user_id, insight.strip(), importance=0.65)
    except Exception as e:
        logger.warning("[memory] compress_and_learn LLM step failed: %s", e)

    # Mark as compressed regardless of whether LLM extraction succeeded
    ids = [m["id"] for m in memories]
    await db.table("memories").update({"compressed": True}).in_("id", ids).execute()
    return len(ids)
