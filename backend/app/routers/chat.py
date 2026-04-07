from __future__ import annotations
import time
import uuid
import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from supabase import AsyncClient
from pydantic import BaseModel, validator
from typing import Optional, List

from ..database import get_db
from ..deps import get_current_user_id
from ..models import MemoryType
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
    user_id: Optional[str] = None  # ignored — user_id comes from auth token
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
async def get_chat_history(user_id: str = Depends(get_current_user_id), limit: int = 50, db: AsyncClient = Depends(get_db)):
    """Return the last N chat messages for a user, in chronological order."""
    res = await (
        db.table("chat_messages")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    messages = list(reversed(res.data or []))
    return [
        {
            "id": m["id"],
            "role": m["role"],
            "content": m["content"],
            "created_at": m["created_at"],
        }
        for m in messages
    ]


@router.post("")
async def chat(req: ChatRequest, db: AsyncClient = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    _rate_limiter.check(user_id)

    # Fetch tasks for context
    tasks_res = await (
        db.table("tasks")
        .select("*")
        .or_(f"assignee_id.eq.{user_id},owner_id.eq.{user_id}")
        .neq("status", "done")
        .order("deadline", desc=False, nullsfirst=False)
        .limit(15)
        .execute()
    )
    tasks_data = [
        {
            "id": t["id"],
            "title": t["title"],
            "status": t["status"],
            "deadline": t.get("deadline"),
            "created_at": t["created_at"],
            "nudge_count": t.get("nudge_count", 0),
            "assignee": req.user_name,
        }
        for t in (tasks_res.data or [])
    ]

    # Fetch memory context
    memories = await get_recent_memories(db, user_id)
    learnings = await get_learnings(db, user_id)

    # Recent nudges for context
    nudges_res = await (
        db.table("nudge_logs")
        .select("*")
        .eq("user_id", user_id)
        .order("sent_at", desc=True)
        .limit(5)
        .execute()
    )
    recent_nudges = [
        {"message": n["message"], "sent_at": n["sent_at"], "response": n.get("user_response")}
        for n in (nudges_res.data or [])
    ]

    # Fetch focal task detail if this chat was triggered by a nudge
    focal_task = None
    if req.focal_task_id:
        ft_res = await (
            db.table("tasks")
            .select("*, owner:users!owner_id(name, id)")
            .eq("id", req.focal_task_id)
            .limit(1)
            .execute()
        )
        if ft_res.data:
            t = ft_res.data[0]
            owner = t.get("owner") or {}
            now = datetime.now(timezone.utc)
            created_str = t.get("created_at", "")
            try:
                created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                days_open = (now - created).days
            except Exception:
                days_open = 0

            deadline_str = None
            dl_raw = t.get("deadline")
            if dl_raw:
                try:
                    dl = datetime.fromisoformat(dl_raw.replace("Z", "+00:00"))
                    if dl.tzinfo is None:
                        dl = dl.replace(tzinfo=timezone.utc)
                    hours_left = (dl - now).total_seconds() / 3600
                    if hours_left < 0:
                        deadline_str = f"OVERDUE by {abs(int(hours_left))}h"
                    elif hours_left < 24:
                        deadline_str = f"Due in {int(hours_left)}h"
                    else:
                        deadline_str = f"Due in {int(hours_left/24)}d"
                except Exception:
                    pass

            # Get last nudge message for this task
            last_nudge_res = await (
                db.table("nudge_logs")
                .select("message")
                .eq("task_id", req.focal_task_id)
                .order("sent_at", desc=True)
                .limit(1)
                .execute()
            )
            last_nudge_msg = last_nudge_res.data[0]["message"] if last_nudge_res.data else None

            focal_task = {
                "id": t["id"],
                "title": t["title"],
                "status": t["status"],
                "days_open": days_open,
                "deadline_str": deadline_str,
                "nudge_count": t.get("nudge_count", 0),
                "is_blocked": t.get("is_blocked") or False,
                "blocked_reason": t.get("blocked_reason"),
                "owner_name": owner.get("name") if owner.get("id") != user_id else None,
                "owner_id": t.get("owner_id") if t.get("owner_id") != user_id else None,
                "last_nudge_message": last_nudge_msg,
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
        logger.error("AI chat failed for user %s: %s", user_id, e, exc_info=True)
        # Still save user message before returning error
        await db.table("chat_messages").insert({
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "role": "user",
            "content": req.message,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        return {
            "reply": "I'm having a moment — could you try again in a few seconds?",
            "task_refs": [],
            "tasks_changed": False,
            "mascot_state": "idle",
        }

    reply = ai_result.get("reply", "...")
    mascot_state = ai_result.get("mascot_state", "listening")
    tasks_changed = False

    # Save learning if AI found one
    if ai_result.get("memory_to_save"):
        await upsert_learning(db, user_id, ai_result["memory_to_save"])

    # Create tasks AI identified
    task_refs = list(ai_result.get("task_refs", []))
    now_iso = datetime.now(timezone.utc).isoformat()

    for t_data in ai_result.get("tasks_to_create", []):
        deadline = None
        if t_data.get("deadline"):
            try:
                dt = datetime.fromisoformat(t_data["deadline"].replace("Z", "+00:00"))
                deadline = dt.isoformat()
            except ValueError:
                pass

        new_task_id = str(uuid.uuid4())
        task_dict = {
            "id": new_task_id,
            "title": t_data["title"],
            "description": t_data.get("description"),
            "deadline": deadline,
            "assignee_id": user_id,
            "owner_id": user_id,
            "source": "chat",
            "is_team_visible": t_data.get("is_team_visible", True),
            "status": "open",
            "created_at": now_iso,
            "updated_at": now_iso,
            "nudge_count": 0,
        }
        t_res = await db.table("tasks").insert(task_dict).execute()
        created_task = t_res.data[0] if t_res.data else task_dict

        await save_memory(
            db=db,
            content=f"Task created from chat: '{t_data['title']}'",
            memory_type=MemoryType.task_event,
            user_id=user_id,
            task_id=created_task["id"],
            importance=0.7,
            ttl_hours=72,
        )

        task_refs.append({"id": created_task["id"], "title": created_task["title"]})
        tasks_changed = True

    # Update tasks AI identified
    for update in ai_result.get("tasks_to_update", []):
        patch: dict = {"updated_at": now_iso}
        if update.get("status"):
            patch["status"] = update["status"]
            if update["status"] == "done":
                patch["completed_at"] = now_iso
                mascot_state = "celebrating"
        u_res = await db.table("tasks").update(patch).eq("id", update["id"]).execute()
        if u_res.data:
            tasks_changed = True
            if update.get("status") == "done":
                t = u_res.data[0]
                try:
                    created_str = t.get("created_at", "")
                    if created_str:
                        created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                        days_taken = (datetime.now(timezone.utc) - created_dt).days
                        nudge_count = t.get("nudge_count", 0)
                        await upsert_learning(
                            db=db,
                            user_id=user_id,
                            content=f"Completed '{t['title']}' in {days_taken} day(s) after {nudge_count} nudge(s)",
                            importance=0.6,
                        )
                except Exception:
                    pass

    # Mark task blocked — AI decided this based on user saying they're stuck
    if ai_result.get("mark_blocked"):
        mb = ai_result["mark_blocked"]
        bt_patch = {
            "is_blocked": True,
            "blocked_reason": mb.get("reason", ""),
            "updated_at": now_iso,
        }
        bt_res = await db.table("tasks").update(bt_patch).eq("id", mb["task_id"]).execute()
        if bt_res.data:
            bt = bt_res.data[0]
            tasks_changed = True
            await save_memory(
                db=db,
                content=f"Task '{bt['title']}' marked blocked: {mb.get('reason', '')}",
                memory_type=MemoryType.task_event,
                user_id=user_id,
                task_id=bt["id"],
                importance=0.8,
                ttl_hours=72,
            )

    # Schedule a follow-up reminder — AI decided user committed to a specific time
    if ai_result.get("schedule_reminder"):
        sr = ai_result["schedule_reminder"]
        minutes = int(sr.get("minutes_from_now", 60))
        reminder_msg = sr.get("message", "Following up on your task")
        task_id_for_reminder = sr.get("task_id")
        from ..scheduler import scheduler
        from apscheduler.triggers.date import DateTrigger
        import uuid as uuid_mod
        reminder_run = datetime.now(timezone.utc) + timedelta(minutes=minutes)

        async def send_reminder(uid: str, msg: str, tid: str | None):
            from ..websocket_manager import ws_manager as _ws
            from ..database import get_db as _get_db
            nudge_id = str(uuid_mod.uuid4())
            rdb = await _get_db()
            await rdb.table("nudge_logs").insert({
                "id": nudge_id,
                "user_id": uid,
                "task_id": tid,
                "message": msg,
                "action_options": "Got it,Let's talk",
                "sent_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
            if uid in _ws.connected_users:
                await _ws.send_nudge(uid, nudge_id, msg, ["Got it", "Let's talk"], tid)

        scheduler.add_job(
            send_reminder,
            trigger=DateTrigger(run_date=reminder_run),
            args=[user_id, reminder_msg, task_id_for_reminder],
            id=f"reminder_{user_id}_{task_id_for_reminder or 'general'}",
            replace_existing=True,
        )

    # Notify owner — AI decided the owner should know about a blocker
    if ai_result.get("notify_owner"):
        no_data = ai_result["notify_owner"]
        nt_res = await db.table("tasks").select("*").eq("id", no_data["task_id"]).limit(1).execute()
        if nt_res.data:
            nt = nt_res.data[0]
            if nt.get("owner_id") and nt["owner_id"] != user_id:
                owner_msg = no_data.get("message", f"{req.user_name or 'Your teammate'} needs help with '{nt['title']}'")
                owner_nudge_id = str(uuid.uuid4())
                await db.table("nudge_logs").insert({
                    "id": owner_nudge_id,
                    "user_id": nt["owner_id"],
                    "task_id": nt["id"],
                    "message": owner_msg,
                    "action_options": "On it,Let's talk",
                    "sent_at": now_iso,
                }).execute()
                if nt["owner_id"] in ws_manager.connected_users:
                    await ws_manager.send_nudge(nt["owner_id"], owner_nudge_id, owner_msg, ["On it", "Let's talk"], nt["id"])

    # Create subtasks — AI decided to break down the task
    if ai_result.get("create_subtasks"):
        for sub in ai_result["create_subtasks"]:
            subtask_id = str(uuid.uuid4())
            subtask_dict = {
                "id": subtask_id,
                "title": sub["title"],
                "description": f"Subtask of: {sub.get('parent_task_id', '')}",
                "assignee_id": user_id,
                "owner_id": user_id,
                "source": "chat",
                "is_team_visible": True,
                "status": "open",
                "created_at": now_iso,
                "updated_at": now_iso,
                "nudge_count": 0,
            }
            sub_res = await db.table("tasks").insert(subtask_dict).execute()
            created_sub = sub_res.data[0] if sub_res.data else subtask_dict
            task_refs.append({"id": created_sub["id"], "title": created_sub["title"]})
            tasks_changed = True

    # Save chat to DB
    chat_rows = [
        {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "role": "user",
            "content": req.message,
            "created_at": now_iso,
        },
        {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "role": "assistant",
            "content": reply,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "task_ids": ",".join(t["id"] for t in task_refs) if task_refs else None,
        },
    ]
    await db.table("chat_messages").insert(chat_rows).execute()

    # Push mascot state update if user is connected
    if user_id in ws_manager.connected_users:
        await ws_manager.send_mascot_state(user_id, mascot_state)

    return {
        "reply": reply,
        "task_refs": task_refs,
        "tasks_changed": tasks_changed,
        "mascot_state": mascot_state,
    }


@router.get("/greeting")
async def get_greeting(user_name: str = "", user_id: str = Depends(get_current_user_id), db: AsyncClient = Depends(get_db)):
    """
    Flaxie speaks first — context-aware opening message when chat opens.
    """
    tasks_res = await (
        db.table("tasks")
        .select("*")
        .eq("assignee_id", user_id)
        .neq("status", "done")
        .order("deadline", desc=False, nullsfirst=False)
        .limit(10)
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
        }
        for t in (tasks_res.data or [])
    ]
    memories = await get_recent_memories(db, user_id)
    learnings = await get_learnings(db, user_id)

    message = await agent_greeting(
        tasks=tasks, memories=memories, learnings=learnings,
        user_name=user_name or None,
    )
    return {"message": message}
