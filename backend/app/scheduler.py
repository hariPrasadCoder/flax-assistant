from __future__ import annotations

"""
Flaxie scheduler — drives the autonomous agent loop.

Every cycle:
1. Load context for the user (tasks, memories, learnings, nudges, calendar, focus state)
2. Run the LangGraph agent — it decides what actions to take
3. Execute whatever the agent decided (send notifications, etc.)
4. Agent tells us when to check next — we schedule accordingly

No hardcoded rules. The agent decides everything — quiet hours, focus mode,
calendar conflicts, recurring tasks, memory compression. We just collect context
and execute whatever the agent decides.
"""

import uuid
import logging
import httpx
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from .database import get_db
from .models import MemoryType
from .ai.agent import run_agent
from .ai.memory import get_recent_memories, get_learnings, save_memory, upsert_learning, compress_and_learn
from .websocket_manager import ws_manager

scheduler = AsyncIOScheduler(timezone="UTC")


async def run_agent_cycle(user_id: str, user_name: str | None = None):
    """
    One full agent cycle for a user.
    Collects all context, hands it to the agent, executes decisions.
    No deterministic filtering here — the agent reasons about time, focus, calendar.
    """
    db = await get_db()

    # Load user info: timezone and focus_until — pass as context, don't filter here
    user_res = await db.table("users").select("*").eq("id", user_id).limit(1).execute()
    user = user_res.data[0] if user_res.data else None
    user_tz = user["timezone"] if user and user.get("timezone") else "UTC"
    focus_until_str = user["focus_until"] if user else None

    # Fetch today's calendar events for context
    calendar_events = []
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                "http://localhost:8747/api/calendar/events",
                params={"user_id": user_id},
            )
            data = r.json()
            calendar_events = data.get("events", [])
    except Exception:
        pass

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    since_24h = (now - timedelta(hours=24)).isoformat()

    # Load active tasks
    tasks_res = await (
        db.table("tasks")
        .select("*")
        .eq("assignee_id", user_id)
        .neq("status", "done")
        .order("deadline", desc=False, nullsfirst=False)
        .execute()
    )
    tasks = [
        {
            "id": t["id"],
            "title": t["title"],
            "status": t["status"],
            "deadline": t.get("deadline"),
            "created_at": t["created_at"],
            "nudge_count": t.get("nudge_count", 0),
            "last_nudged_at": t.get("last_nudged_at"),
            "assignee": user_name,
            "priority": t.get("priority") if t.get("priority") is not None else 3,
            "is_blocked": t.get("is_blocked") or False,
            "blocked_reason": t.get("blocked_reason"),
        }
        for t in (tasks_res.data or [])
    ]

    # Tasks this user OWNS that are assigned to someone else
    owned_res = await (
        db.table("tasks")
        .select("*, assignee:users!assignee_id(name)")
        .eq("owner_id", user_id)
        .neq("assignee_id", user_id)
        .neq("status", "done")
        .order("deadline", desc=False, nullsfirst=False)
        .execute()
    )
    owned_tasks = []
    for t in (owned_res.data or []):
        assignee_info = t.get("assignee") or {}
        owned_tasks.append({
            "id": t["id"],
            "title": t["title"],
            "status": t["status"],
            "deadline": t.get("deadline"),
            "created_at": t["created_at"],
            "nudge_count": t.get("nudge_count", 0),
            "last_nudged_at": t.get("last_nudged_at"),
            "assignee": assignee_info.get("name") if isinstance(assignee_info, dict) else None,
            "assignee_id": t.get("assignee_id"),
            "priority": t.get("priority") if t.get("priority") is not None else 3,
        })

    # Load recent nudges (24h)
    nudge_res = await (
        db.table("nudge_logs")
        .select("*")
        .eq("user_id", user_id)
        .gte("sent_at", since_24h)
        .order("sent_at", desc=True)
        .limit(10)
        .execute()
    )
    recent_nudges = [
        {
            "message": n["message"],
            "sent_at": n["sent_at"],
            "response": n.get("user_response"),
            "task_id": n.get("task_id"),
        }
        for n in (nudge_res.data or [])
    ]

    # Load memories
    memories = await get_recent_memories(db, user_id)
    learnings = await get_learnings(db, user_id)

    # Run the agent — it decides whether to nudge, stay silent, etc.
    result = await run_agent(
        tasks=tasks,
        memories=memories,
        learnings=learnings,
        recent_nudges=recent_nudges,
        user_name=user_name,
        owned_tasks=owned_tasks,
        user_id=user_id,
        user_tz=user_tz,
        calendar_events=calendar_events,
        focus_until=focus_until_str,
    )

    mascot_state = result.get("mascot_state", "idle")
    next_check_minutes = result.get("next_check_minutes", 30)
    actions = result.get("actions", [])

    # Push mascot state
    if user_id in ws_manager.connected_users:
        await ws_manager.send_mascot_state(user_id, mascot_state)

    # Execute each action the agent decided on
    for action in actions:
        tool_name = action.get("tool")
        message = action.get("message", "")
        action_options = action.get("action_options", ["Got it", "Let's talk"])
        task_id = action.get("task_id")

        if tool_name in ("send_notification", "ask_checkin", "celebrate", "suggest_breakdown"):
            if user_id not in ws_manager.connected_users:
                continue

            nudge_id = str(uuid.uuid4())

            # Record nudge in DB
            await db.table("nudge_logs").insert({
                "id": nudge_id,
                "user_id": user_id,
                "task_id": task_id,
                "message": message,
                "action_options": ",".join(action_options),
                "sent_at": now_iso,
            }).execute()

            # Update task nudge tracking — fetch current count first, then increment
            if task_id:
                task_fetch = await db.table("tasks").select("nudge_count").eq("id", task_id).limit(1).execute()
                if task_fetch.data:
                    current_count = task_fetch.data[0].get("nudge_count") or 0
                    await db.table("tasks").update({
                        "nudge_count": current_count + 1,
                        "last_nudged_at": now_iso,
                    }).eq("id", task_id).execute()

            # Save to memory
            await save_memory(
                db=db,
                content=f"Flaxie sent notification: {message}",
                memory_type=MemoryType.task_event,
                user_id=user_id,
                task_id=task_id,
                importance=0.6,
                ttl_hours=48,
            )

            # Push to desktop
            await ws_manager.send_nudge(
                user_id=user_id,
                nudge_id=nudge_id,
                message=message,
                action_options=action_options,
                task_id=task_id,
            )
            logger.info("[agent] notified %s: %s...", user_id, message[:60])

        elif tool_name == "compress_memories":
            # Agent decided to compress — actually summarize into learnings via LLM
            count = await compress_and_learn(db, user_id)
            logger.info("[agent] compressed %d memories into learnings for %s", count, user_id)

        elif tool_name == "set_focus_mode":
            # Agent set focus mode — already executed via HTTP in the tool itself
            minutes = action.get("minutes", 0)
            logger.info("[agent] focus mode set for %s (%dmin)", user_id, minutes)

    # Agent decides when to run next
    next_run = datetime.now(timezone.utc) + timedelta(minutes=next_check_minutes)
    scheduler.add_job(
        run_agent_cycle,
        trigger=DateTrigger(run_date=next_run),
        args=[user_id, user_name],
        id=f"agent_{user_id}",
        replace_existing=True,
    )
    logger.info("[agent] cycle done for %s | state=%s | next=%dmin | actions=%d", user_id, mascot_state, next_check_minutes, len(actions))


async def run_reflection_cycle(user_id: str, user_name: str | None = None):
    """
    Deep thinking cycle — runs once a day.
    Agent reviews the week, surfaces a genuine insight to chat if warranted.
    Completely separate from the nudge cycle — different goal, different cadence.
    """
    from .ai.brain import reflect
    import uuid as _uuid

    logger.info("[reflection] starting cycle for %s", user_id)

    db = await get_db()

    # Load user context
    user_res = await db.table("users").select("*").eq("id", user_id).limit(1).execute()
    if not user_res.data:
        return

    user = user_res.data[0]
    user_tz = user.get("timezone") or "UTC"
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    since_7d = (now - timedelta(days=7)).isoformat()

    # Load open tasks
    open_res = await (
        db.table("tasks")
        .select("*")
        .eq("assignee_id", user_id)
        .neq("status", "done")
        .order("deadline", desc=False, nullsfirst=False)
        .execute()
    )
    tasks = [
        {
            "id": t["id"],
            "title": t["title"],
            "status": t["status"],
            "deadline": t.get("deadline"),
            "created_at": t["created_at"],
            "nudge_count": t.get("nudge_count", 0),
            "assignee": user_name,
            "is_blocked": t.get("is_blocked") or False,
        }
        for t in (open_res.data or [])
    ]

    # Load tasks completed in the last 7 days
    done_res = await (
        db.table("tasks")
        .select("*")
        .eq("assignee_id", user_id)
        .eq("status", "done")
        .gte("updated_at", since_7d)
        .order("updated_at", desc=True)
        .limit(20)
        .execute()
    )
    done_tasks = [
        {"id": t["id"], "title": t["title"], "completed_at": t.get("updated_at")}
        for t in (done_res.data or [])
    ]

    # Load nudges from last 7 days
    nudge_res = await (
        db.table("nudge_logs")
        .select("*")
        .eq("user_id", user_id)
        .gte("sent_at", since_7d)
        .order("sent_at", desc=True)
        .limit(20)
        .execute()
    )
    recent_nudges = [
        {"message": n["message"], "sent_at": n["sent_at"], "response": n.get("user_response")}
        for n in (nudge_res.data or [])
    ]

    memories = await get_recent_memories(db, user_id)
    learnings = await get_learnings(db, user_id)

    # Run the reflection
    result = await reflect(
        tasks=tasks,
        done_tasks=done_tasks,
        memories=memories,
        learnings=learnings,
        recent_nudges=recent_nudges,
        user_name=user_name,
        user_tz=user_tz,
        days_to_review=7,
    )

    next_hours = result.get("next_reflection_hours", 24)

    # Always persist any behavioral insights the reflection surfaced
    for learning in result.get("learnings_to_save", []):
        if isinstance(learning, str) and learning.strip():
            await upsert_learning(db, user_id, learning.strip(), importance=0.75)

    if result.get("should_share") and result.get("message"):
        message = result["message"]

        # Save as a chat message from Flaxie — appears in chat when user opens
        msg_id = str(_uuid.uuid4())
        await db.table("chat_messages").insert({
            "id": msg_id,
            "user_id": user_id,
            "role": "assistant",
            "content": message,
            "created_at": now_iso,
        }).execute()

        # Also save to memory so future cycles know this was shared
        await save_memory(
            db=db,
            content=f"Flaxie weekly reflection: {message}",
            memory_type=MemoryType.conversation,
            user_id=user_id,
            importance=0.8,
            ttl_hours=168,  # 7 days
        )

        # Push live if user is connected — as a chat message, not a notification
        if user_id in ws_manager.connected_users:
            await ws_manager.send_reflection(user_id, message, result.get("mascot_state", "idle"))

        logger.info("[reflection] insight shared for %s: %s...", user_id, message[:60])
    else:
        logger.info("[reflection] nothing meaningful to share for %s", user_id)

    # Update last_reflection_at
    await db.table("users").update({"last_reflection_at": now_iso}).eq("id", user_id).execute()

    # Schedule next reflection — agent decided the timing
    next_run = datetime.now(timezone.utc) + timedelta(hours=next_hours)
    scheduler.add_job(
        run_reflection_cycle,
        trigger=DateTrigger(run_date=next_run),
        args=[user_id, user_name],
        id=f"reflect_{user_id}",
        replace_existing=True,
    )
    logger.info("[reflection] next cycle for %s in %dh", user_id, next_hours)


async def register_user_for_nudges(user_id: str, user_name: str | None = None):
    """Start the agent cycle when a user connects via WebSocket."""
    try:
        scheduler.remove_job(f"agent_{user_id}")
    except Exception:
        pass

    # First nudge cycle in 20s
    first_run = datetime.now(timezone.utc) + timedelta(seconds=20)
    scheduler.add_job(
        run_agent_cycle,
        trigger=DateTrigger(run_date=first_run),
        args=[user_id, user_name],
        id=f"agent_{user_id}",
        replace_existing=True,
    )

    # First reflection in 6 hours (not immediately — needs data to reflect on)
    # Subsequent reflections are agent-decided (18-36h)
    try:
        scheduler.remove_job(f"reflect_{user_id}")
    except Exception:
        pass
    reflect_run = datetime.now(timezone.utc) + timedelta(hours=6)
    scheduler.add_job(
        run_reflection_cycle,
        trigger=DateTrigger(run_date=reflect_run),
        args=[user_id, user_name],
        id=f"reflect_{user_id}",
        replace_existing=True,
    )
    logger.info("[scheduler] registered nudge + reflection cycles for %s", user_id)


def start_scheduler():
    if not scheduler.running:
        scheduler.start()
        # No cron jobs here — the agent handles recurring tasks and memory compression
        # as autonomous decisions via create_task_instance and compress_memories tools.
        logger.info("[scheduler] started")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
