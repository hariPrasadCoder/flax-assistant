import time
import uuid
import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, validator
from typing import Optional, List

from ..database import get_db, AsyncSessionLocal
from ..models import Task, TaskStatus, MemoryType, ChatMessage, NudgeLog, User
from ..ai.brain import chat as ai_chat
from ..ai.agent import agent_greeting
from ..ai.memory import get_recent_memories, get_learnings, save_memory, upsert_learning
from ..websocket_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


# Simple in-memory rate limiter — 20 requests per user per minute
class _RateLimiter:
    def __init__(self, max_requests: int = 20, window_seconds: int = 60):
        self._counts: dict = defaultdict(lambda: [0, 0.0])
        self._max = max_requests
        self._window = window_seconds

    def check(self, user_id: str) -> None:
        now = time.monotonic()
        count, window_start = self._counts[user_id]
        if now - window_start > self._window:
            self._counts[user_id] = [1, now]
            return
        if count >= self._max:
            raise HTTPException(status_code=429, detail="Too many requests — slow down a bit")
        self._counts[user_id][0] += 1


_rate_limiter = _RateLimiter()


class ChatRequest(BaseModel):
    message: str
    user_id: str
    user_name: Optional[str] = None
    history: list[dict] = []
    nudge_context: Optional[str] = None   # nudge message that triggered this chat
    focal_task_id: Optional[str] = None   # task_id the nudge was about

    @validator('message')
    def message_not_empty(cls, v):
        if not v.strip():
            raise ValueError('Message cannot be empty')
        return v[:4000]  # truncate to 4000 chars max

    @validator('history')
    def history_limit(cls, v):
        return v[-20:]  # keep last 20 messages max


@router.get("/history")
async def get_chat_history(user_id: str, limit: int = 50, db: AsyncSession = Depends(get_db)):
    """Return the last N chat messages for a user, in chronological order."""
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.user_id == user_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )
    messages = result.scalars().all()
    # Reverse to return chronological order
    messages = list(reversed(messages))
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat(),
        }
        for m in messages
    ]


@router.post("")
async def chat(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    _rate_limiter.check(req.user_id)

    # Fetch tasks for context
    result = await db.execute(
        select(Task)
        .where(
            (Task.assignee_id == req.user_id) | (Task.owner_id == req.user_id),
            Task.status != TaskStatus.done,
        )
        .order_by(Task.deadline.asc().nullslast())
        .limit(15)
    )
    tasks = result.scalars().all()
    tasks_data = [
        {
            "id": t.id,
            "title": t.title,
            "status": t.status.value,
            "deadline": t.deadline.isoformat() if t.deadline else None,
            "created_at": t.created_at.isoformat(),
            "nudge_count": t.nudge_count,
            "assignee": req.user_name,
        }
        for t in tasks
    ]

    # Fetch memory context
    memories = await get_recent_memories(db, req.user_id)
    learnings = await get_learnings(db, req.user_id)

    # Recent nudges for context
    recent_nudges_result = await db.execute(
        select(NudgeLog)
        .where(NudgeLog.user_id == req.user_id)
        .order_by(NudgeLog.sent_at.desc())
        .limit(5)
    )
    recent_nudges = [
        {"message": n.message, "sent_at": n.sent_at.isoformat(), "response": n.user_response}
        for n in recent_nudges_result.scalars().all()
    ]

    # Fetch focal task detail if this chat was triggered by a nudge
    focal_task = None
    if req.focal_task_id:
        ft_result = await db.execute(
            select(Task, User)
            .join(User, Task.owner_id == User.id, isouter=True)
            .where(Task.id == req.focal_task_id)
        )
        row = ft_result.first()
        if row:
            t, owner = row
            now = datetime.now(timezone.utc)
            created = t.created_at.replace(tzinfo=timezone.utc) if t.created_at.tzinfo is None else t.created_at
            days_open = (now - created).days
            deadline_str = None
            if t.deadline:
                dl = t.deadline.replace(tzinfo=timezone.utc) if t.deadline.tzinfo is None else t.deadline
                hours_left = (dl - now).total_seconds() / 3600
                if hours_left < 0:
                    deadline_str = f"OVERDUE by {abs(int(hours_left))}h"
                elif hours_left < 24:
                    deadline_str = f"Due in {int(hours_left)}h"
                else:
                    deadline_str = f"Due in {int(hours_left/24)}d"

            # Get last nudge message for this task
            last_nudge_result = await db.execute(
                select(NudgeLog)
                .where(NudgeLog.task_id == req.focal_task_id)
                .order_by(NudgeLog.sent_at.desc())
                .limit(1)
            )
            last_nudge = last_nudge_result.scalar_one_or_none()

            focal_task = {
                "id": t.id,
                "title": t.title,
                "status": t.status.value,
                "days_open": days_open,
                "deadline_str": deadline_str,
                "nudge_count": t.nudge_count,
                "is_blocked": t.is_blocked or False,
                "blocked_reason": t.blocked_reason,
                "owner_name": owner.name if owner and owner.id != req.user_id else None,
                "owner_id": t.owner_id if t.owner_id != req.user_id else None,
                "last_nudge_message": last_nudge.message if last_nudge else None,
            }

    # Call AI
    try:
        ai_result = await ai_chat(
            user_message=req.message,
            history=req.history,
            tasks=tasks_data,
            memories=memories,
            learnings=learnings,
            recent_nudges=recent_nudges,
            user_name=req.user_name,
            nudge_context=req.nudge_context,
            focal_task=focal_task,
        )
    except Exception as e:
        logger.error("AI chat failed for user %s: %s", req.user_id, e, exc_info=True)
        # Still save user message before returning error
        db.add(ChatMessage(id=str(uuid.uuid4()), user_id=req.user_id, role="user", content=req.message))
        await db.commit()
        return {
            "reply": "I'm having a moment — could you try again in a few seconds?",
            "task_refs": [],
            "tasks_changed": False,
            "mascot_state": "idle",
        }

    reply = ai_result.get("reply", "...")
    mascot_state = ai_result.get("mascot_state", "listening")
    tasks_changed = False

    # Save user message to memory
    await save_memory(
        db=db,
        content=f"User said: {req.message}",
        memory_type=MemoryType.conversation,
        user_id=req.user_id,
        importance=0.5,
        ttl_hours=48,
    )

    # Save assistant reply to memory
    await save_memory(
        db=db,
        content=f"Flaxie replied: {reply}",
        memory_type=MemoryType.conversation,
        user_id=req.user_id,
        importance=0.4,
        ttl_hours=48,
    )

    # Save learning if AI found one
    if ai_result.get("memory_to_save"):
        await upsert_learning(db, req.user_id, ai_result["memory_to_save"])

    # Create tasks AI identified
    task_refs = list(ai_result.get("task_refs", []))
    for t_data in ai_result.get("tasks_to_create", []):
        deadline = None
        if t_data.get("deadline"):
            try:
                deadline = datetime.fromisoformat(t_data["deadline"].replace("Z", "+00:00"))
            except ValueError:
                pass

        task = Task(
            title=t_data["title"],
            description=t_data.get("description"),
            deadline=deadline,
            assignee_id=req.user_id,
            owner_id=req.user_id,
            source="chat",
            is_team_visible=t_data.get("is_team_visible", True),
        )
        db.add(task)
        await db.flush()

        await save_memory(
            db=db,
            content=f"Task created from chat: '{t_data['title']}'",
            memory_type=MemoryType.task_event,
            user_id=req.user_id,
            task_id=task.id,
            importance=0.7,
            ttl_hours=72,
        )

        task_refs.append({"id": task.id, "title": task.title})
        tasks_changed = True

    # Update tasks AI identified
    for update in ai_result.get("tasks_to_update", []):
        task_result = await db.execute(select(Task).where(Task.id == update["id"]))
        task = task_result.scalar_one_or_none()
        if task:
            if update.get("status"):
                task.status = TaskStatus(update["status"])
                if update["status"] == "done":
                    task.completed_at = datetime.utcnow()
                    # Celebrate!
                    mascot_state = "celebrating"
            task.updated_at = datetime.utcnow()
            tasks_changed = True

    # Mark task blocked — AI decided this based on user saying they're stuck
    if ai_result.get("mark_blocked"):
        mb = ai_result["mark_blocked"]
        bt_result = await db.execute(select(Task).where(Task.id == mb["task_id"]))
        bt = bt_result.scalar_one_or_none()
        if bt:
            bt.is_blocked = True
            bt.blocked_reason = mb.get("reason", "")
            bt.updated_at = datetime.utcnow()
            tasks_changed = True
            await save_memory(
                db=db,
                content=f"Task '{bt.title}' marked blocked: {mb.get('reason', '')}",
                memory_type=MemoryType.task_event,
                user_id=req.user_id,
                task_id=bt.id,
                importance=0.8,
                ttl_hours=72,
            )

    # Schedule a follow-up reminder — AI decided user committed to a specific time
    if ai_result.get("schedule_reminder"):
        sr = ai_result["schedule_reminder"]
        minutes = int(sr.get("minutes_from_now", 60))
        reminder_msg = sr.get("message", f"Following up on your task")
        task_id_for_reminder = sr.get("task_id")
        from ..scheduler import scheduler
        from apscheduler.triggers.date import DateTrigger
        import uuid as uuid_mod
        reminder_run = datetime.now(timezone.utc) + timedelta(minutes=minutes)

        async def send_reminder(uid: str, msg: str, tid: str | None):
            from ..websocket_manager import ws_manager as _ws
            nudge_id = str(uuid_mod.uuid4())
            async with AsyncSessionLocal() as rdb:
                from ..models import NudgeLog as NLog
                nl = NLog(id=nudge_id, user_id=uid, task_id=tid, message=msg,
                         action_options="Got it,Let's talk")
                rdb.add(nl)
                await rdb.commit()
            if uid in _ws.connected_users:
                await _ws.send_nudge(uid, nudge_id, msg, ["Got it", "Let's talk"], tid)

        scheduler.add_job(
            send_reminder,
            trigger=DateTrigger(run_date=reminder_run),
            args=[req.user_id, reminder_msg, task_id_for_reminder],
            id=f"reminder_{req.user_id}_{task_id_for_reminder or 'general'}",
            replace_existing=True,
        )

    # Notify owner — AI decided the owner should know about a blocker
    if ai_result.get("notify_owner"):
        no_data = ai_result["notify_owner"]
        nt_result = await db.execute(select(Task).where(Task.id == no_data["task_id"]))
        nt = nt_result.scalar_one_or_none()
        if nt and nt.owner_id and nt.owner_id != req.user_id:
            owner_msg = no_data.get("message", f"{req.user_name or 'Your teammate'} needs help with '{nt.title}'")
            import uuid as uuid_mod2
            owner_nudge_id = str(uuid_mod2.uuid4())
            owner_nudge = NudgeLog(
                id=owner_nudge_id,
                user_id=nt.owner_id,
                task_id=nt.id,
                message=owner_msg,
                action_options="On it,Let's talk",
            )
            db.add(owner_nudge)
            if nt.owner_id in ws_manager.connected_users:
                await ws_manager.send_nudge(nt.owner_id, owner_nudge_id, owner_msg, ["On it", "Let's talk"], nt.id)

    # Create subtasks — AI decided to break down the task
    if ai_result.get("create_subtasks"):
        for sub in ai_result["create_subtasks"]:
            subtask = Task(
                title=sub["title"],
                description=f"Subtask of: {sub.get('parent_task_id', '')}",
                assignee_id=req.user_id,
                owner_id=req.user_id,
                source="chat",
                is_team_visible=True,
            )
            db.add(subtask)
            await db.flush()
            task_refs.append({"id": subtask.id, "title": subtask.title})
            tasks_changed = True

    # Save chat to DB
    db.add(ChatMessage(
        id=str(uuid.uuid4()),
        user_id=req.user_id,
        role="user",
        content=req.message,
    ))
    db.add(ChatMessage(
        id=str(uuid.uuid4()),
        user_id=req.user_id,
        role="assistant",
        content=reply,
        task_ids=",".join(t["id"] for t in task_refs) if task_refs else None,
    ))

    await db.commit()

    # Push mascot state update if user is connected
    if req.user_id in ws_manager.connected_users:
        await ws_manager.send_mascot_state(req.user_id, mascot_state)

    return {
        "reply": reply,
        "task_refs": task_refs,
        "tasks_changed": tasks_changed,
        "mascot_state": mascot_state,
    }


@router.get("/greeting")
async def get_greeting(user_id: str, user_name: str = "", db: AsyncSession = Depends(get_db)):
    """
    Flaxie speaks first — context-aware opening message when chat opens.
    """
    result = await db.execute(
        select(Task)
        .where(Task.assignee_id == user_id, Task.status != TaskStatus.done)
        .order_by(Task.deadline.asc().nullslast())
        .limit(10)
    )
    tasks = [
        {
            "id": t.id, "title": t.title, "status": t.status.value,
            "deadline": t.deadline.isoformat() if t.deadline else None,
            "created_at": t.created_at.isoformat(), "nudge_count": t.nudge_count,
        }
        for t in result.scalars().all()
    ]
    memories = await get_recent_memories(db, user_id)
    learnings = await get_learnings(db, user_id)

    message = await agent_greeting(
        tasks=tasks, memories=memories, learnings=learnings,
        user_name=user_name or None,
    )
    return {"message": message}
