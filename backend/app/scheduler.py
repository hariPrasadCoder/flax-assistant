from __future__ import annotations

"""
Flaxie scheduler — drives the autonomous agent loop.

Every cycle:
1. Load context for the user (tasks, memories, learnings, nudges)
2. Run the LangGraph agent — it decides what actions to take
3. Execute whatever the agent decided (send notifications, etc.)
4. Agent tells us when to check next — we schedule accordingly

No hardcoded rules. The agent decides everything.
"""

import uuid
import httpx
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

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
    The agent decides what to do; we execute its decisions.
    """
    # Load user info: timezone and focus_until
    async with AsyncSessionLocal() as db:
        user_res = await db.execute(select(User).where(User.id == user_id))
        user = user_res.scalar_one_or_none()
        user_tz = user.timezone if user and user.timezone else "UTC"
        focus_until = user.focus_until if user else None

    now_utc = datetime.now(timezone.utc)

    # Focus / DND check
    if focus_until is not None:
        focus_until_aware = focus_until.replace(tzinfo=timezone.utc)
        if now_utc < focus_until_aware:
            print(f"[agent] user {user_id} is in focus mode until {focus_until}")
            # Reschedule for when focus ends + 5 min
            next_run = focus_until_aware + timedelta(minutes=5)
            scheduler.add_job(
                run_agent_cycle,
                trigger=DateTrigger(run_date=next_run),
                args=[user_id, user_name],
                id=f"agent_{user_id}",
                replace_existing=True,
            )
            return

    # Quiet hours check — skip nudging between 9pm and 8am local time
    try:
        local_now = datetime.now(ZoneInfo(user_tz))
        hour = local_now.hour
        if hour < 8 or hour >= 21:
            # Reschedule for 8am local time tomorrow (or today if it's past midnight but before 8am)
            if hour < 8:
                next_local = local_now.replace(hour=8, minute=0, second=0, microsecond=0)
            else:
                next_local = (local_now + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
            next_run = next_local.astimezone(timezone.utc).replace(tzinfo=timezone.utc)
            scheduler.add_job(
                run_agent_cycle,
                trigger=DateTrigger(run_date=next_run),
                args=[user_id, user_name],
                id=f"agent_{user_id}",
                replace_existing=True,
            )
            print(f"[agent] quiet hours for {user_id} ({user_tz}, {hour}h) — next run at 8am local")
            return
    except Exception as e:
        print(f"[agent] timezone error for {user_id}: {e}")

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
                "is_recurring": t.is_recurring or False,
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

        # Run the agent
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
                print(f"[agent] notified {user_id}: {message[:60]}...")

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
    print(f"[agent] cycle done for {user_id} | state={mascot_state} | next={next_check_minutes}min | actions={len(actions)}")


async def register_user_for_nudges(user_id: str, user_name: str | None = None):
    """Start the agent cycle when a user connects via WebSocket."""
    try:
        scheduler.remove_job(f"agent_{user_id}")
    except Exception:
        pass

    # First cycle in 20s — let them settle
    first_run = datetime.now(timezone.utc) + timedelta(seconds=20)
    scheduler.add_job(
        run_agent_cycle,
        trigger=DateTrigger(run_date=first_run),
        args=[user_id, user_name],
        id=f"agent_{user_id}",
        replace_existing=True,
    )
    print(f"[agent] registered cycle for {user_id}")


async def process_recurring_tasks():
    """Create new instances of recurring tasks that are due."""
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(Task).where(
                Task.is_recurring == True,
                Task.status == TaskStatus.done,
            )
        )
        for task in result.scalars().all():
            if task.recurrence_days and task.completed_at:
                next_due = task.completed_at + timedelta(days=task.recurrence_days)
                if next_due <= now + timedelta(hours=24):
                    new_task = Task(
                        title=task.title,
                        description=task.description,
                        assignee_id=task.assignee_id,
                        owner_id=task.owner_id,
                        team_id=task.team_id,
                        priority=task.priority,
                        is_recurring=True,
                        recurrence_days=task.recurrence_days,
                        deadline=next_due,
                        source="recurring",
                    )
                    db.add(new_task)
        await db.commit()
    print("[scheduler] process_recurring_tasks done")


async def compress_memories():
    """Summarize old uncompressed memories into learnings."""
    async with AsyncSessionLocal() as db:
        # Get all users with recent memories
        users_result = await db.execute(select(User))
        for user in users_result.scalars().all():
            memories_result = await db.execute(
                select(Memory).where(
                    Memory.user_id == user.id,
                    Memory.compressed == False,
                    Memory.type != MemoryType.learning,
                    Memory.created_at < datetime.utcnow() - timedelta(hours=48),
                ).limit(20)
            )
            old_memories = memories_result.scalars().all()
            if len(old_memories) >= 5:
                for m in old_memories:
                    m.compressed = True
                await db.commit()
                print(f"[memory] compressed {len(old_memories)} memories for {user.id}")


def start_scheduler():
    if not scheduler.running:
        scheduler.start()
        # Daily recurring tasks job at 00:05 UTC
        scheduler.add_job(
            process_recurring_tasks,
            "cron",
            hour=0,
            minute=5,
            id="recurring_tasks",
            replace_existing=True,
        )
        # Memory compression every 6 hours
        scheduler.add_job(
            compress_memories,
            "interval",
            hours=6,
            id="compress_memories",
            replace_existing=True,
        )
        print("[scheduler] started")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
