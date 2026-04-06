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
from sqlalchemy import select

from .database import AsyncSessionLocal
from .models import Task, TaskStatus, NudgeLog, MemoryType, Memory, User
from .ai.agent import run_agent
from .ai.memory import get_recent_memories, get_learnings, save_memory
from .websocket_manager import ws_manager

scheduler = AsyncIOScheduler(timezone="UTC")


async def run_agent_cycle(user_id: str, user_name: str | None = None):
    """
    One full agent cycle for a user.
    Collects all context, hands it to the agent, executes decisions.
    No deterministic filtering here — the agent reasons about time, focus, calendar.
    """
    # Load user info: timezone and focus_until — pass as context, don't filter here
    async with AsyncSessionLocal() as db:
        user_res = await db.execute(select(User).where(User.id == user_id))
        user = user_res.scalar_one_or_none()
        user_tz = user.timezone if user and user.timezone else "UTC"
        focus_until = user.focus_until if user else None

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

    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)

        # Load active tasks
        result = await db.execute(
            select(Task)
            .where(Task.assignee_id == user_id, Task.status != TaskStatus.done)
            .order_by(Task.deadline.asc().nullslast())
        )
        tasks = [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status.value,
                "deadline": t.deadline.isoformat() if t.deadline else None,
                "created_at": t.created_at.isoformat(),
                "nudge_count": t.nudge_count,
                "last_nudged_at": t.last_nudged_at.isoformat() if t.last_nudged_at else None,
                "assignee": user_name,
                "priority": t.priority if t.priority is not None else 3,
                "is_blocked": t.is_blocked or False,
                "blocked_reason": t.blocked_reason,
            }
            for t in result.scalars().all()
        ]

        # Tasks this user OWNS that are assigned to someone else
        owned_result = await db.execute(
            select(Task, User)
            .join(User, Task.assignee_id == User.id)
            .where(
                Task.owner_id == user_id,
                Task.assignee_id != user_id,
                Task.status != TaskStatus.done
            )
            .order_by(Task.deadline.asc().nullslast())
        )
        owned_tasks = [
            {
                "id": t.id, "title": t.title, "status": t.status.value,
                "deadline": t.deadline.isoformat() if t.deadline else None,
                "created_at": t.created_at.isoformat(),
                "nudge_count": t.nudge_count,
                "last_nudged_at": t.last_nudged_at.isoformat() if t.last_nudged_at else None,
                "assignee": u.name,  # who's doing the work
                "assignee_id": t.assignee_id,
                "priority": t.priority if t.priority is not None else 3,
            }
            for t, u in owned_result.all()
        ]

        # Load recent nudges (24h)
        nudge_result = await db.execute(
            select(NudgeLog)
            .where(NudgeLog.user_id == user_id, NudgeLog.sent_at >= now - timedelta(hours=24))
            .order_by(NudgeLog.sent_at.desc())
            .limit(10)
        )
        recent_nudges = [
            {
                "message": n.message,
                "sent_at": n.sent_at.isoformat(),
                "response": n.user_response,
                "task_id": n.task_id,
            }
            for n in nudge_result.scalars().all()
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
            focus_until=focus_until.isoformat() if focus_until else None,
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
                nudge_log = NudgeLog(
                    id=nudge_id,
                    user_id=user_id,
                    task_id=task_id,
                    message=message,
                    action_options=",".join(action_options),
                )
                db.add(nudge_log)

                # Update task nudge tracking
                if task_id:
                    task_res = await db.execute(select(Task).where(Task.id == task_id))
                    task = task_res.scalar_one_or_none()
                    if task:
                        task.nudge_count += 1
                        task.last_nudged_at = now

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
                # Agent decided to compress old memories
                old_memories_res = await db.execute(
                    select(Memory).where(
                        Memory.user_id == user_id,
                        Memory.compressed == False,
                        Memory.type != MemoryType.learning,
                        Memory.created_at < now - timedelta(hours=24),
                    ).limit(15)
                )
                compressed_count = 0
                for m in old_memories_res.scalars().all():
                    m.compressed = True
                    compressed_count += 1
                logger.info("[agent] compressed %d memories for %s", compressed_count, user_id)

            elif tool_name == "set_focus_mode":
                # Agent set focus mode — already executed via HTTP in the tool itself
                minutes = action.get("minutes", 0)
                logger.info("[agent] focus mode set for %s (%dmin)", user_id, minutes)

        await db.commit()

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
    from .models import ChatMessage
    import uuid

    logger.info("[reflection] starting cycle for %s", user_id)

    async with AsyncSessionLocal() as db:
        # Load user context
        user_res = await db.execute(select(User).where(User.id == user_id))
        user = user_res.scalar_one_or_none()
        if not user:
            return

        user_tz = user.timezone if user and user.timezone else "UTC"
        now = datetime.now(timezone.utc)

        # Load open tasks
        open_result = await db.execute(
            select(Task)
            .where(Task.assignee_id == user_id, Task.status != TaskStatus.done)
            .order_by(Task.deadline.asc().nullslast())
        )
        tasks = [
            {
                "id": t.id, "title": t.title, "status": t.status.value,
                "deadline": t.deadline.isoformat() if t.deadline else None,
                "created_at": t.created_at.isoformat(),
                "nudge_count": t.nudge_count,
                "assignee": user_name,
                "is_blocked": t.is_blocked or False,
            }
            for t in open_result.scalars().all()
        ]

        # Load tasks completed in the last 7 days
        done_result = await db.execute(
            select(Task)
            .where(
                Task.assignee_id == user_id,
                Task.status == TaskStatus.done,
                Task.updated_at >= now - timedelta(days=7),
            )
            .order_by(Task.updated_at.desc())
            .limit(20)
        )
        done_tasks = [
            {"id": t.id, "title": t.title, "completed_at": t.updated_at.isoformat() if t.updated_at else None}
            for t in done_result.scalars().all()
        ]

        # Load nudges from last 7 days
        nudge_result = await db.execute(
            select(NudgeLog)
            .where(NudgeLog.user_id == user_id, NudgeLog.sent_at >= now - timedelta(days=7))
            .order_by(NudgeLog.sent_at.desc())
            .limit(20)
        )
        recent_nudges = [
            {"message": n.message, "sent_at": n.sent_at.isoformat(), "response": n.user_response}
            for n in nudge_result.scalars().all()
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

        if result.get("should_share") and result.get("message"):
            message = result["message"]

            # Save as a chat message from Flaxie — appears in chat when user opens
            msg_id = str(uuid.uuid4())
            db.add(ChatMessage(
                id=msg_id,
                user_id=user_id,
                role="assistant",
                content=message,
            ))

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
        user.last_reflection_at = now
        await db.commit()

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
