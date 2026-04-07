import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from supabase import AsyncClient
from pydantic import BaseModel

from ..database import get_db
from ..deps import get_current_user_id
from ..models import MemoryType
from ..ai.memory import save_memory, upsert_learning
from ..websocket_manager import ws_manager

router = APIRouter(prefix="/api/nudges", tags=["nudges"])


class RespondRequest(BaseModel):
    response: str


def infer_action_type(label: str) -> str:
    """Infer action type from button label using heuristics."""
    lower = label.lower()
    if any(w in lower for w in ["done", "finished", "complete", "wrapped"]):
        return "done"
    if any(w in lower for w in ["help", "blocked", "stuck", "struggling"]):
        return "help"
    if any(w in lower for w in ["snooze", "remind me", "later", "1h", "2h", "30m"]):
        return "snooze"
    if any(w in lower for w in ["let's talk", "chat"]):
        return "chat"
    if any(w in lower for w in ["remind them", "ping them", "remind her", "remind him", "nudge them"]):
        return "remind_assignee"
    return "ack"


@router.get("/history")
async def get_nudge_history(user_id: str = Depends(get_current_user_id), limit: int = 20, db: AsyncClient = Depends(get_db)):
    """Return the last N nudges for a user."""
    res = await (
        db.table("nudge_logs")
        .select("*")
        .eq("user_id", user_id)
        .order("sent_at", desc=True)
        .limit(limit)
        .execute()
    )
    nudges = res.data or []
    return [
        {
            "id": n["id"],
            "message": n["message"],
            "sent_at": n["sent_at"],
            "user_response": n.get("user_response"),
            "responded_at": n.get("responded_at"),
            "dismissed": n.get("dismissed", False),
            "task_id": n.get("task_id"),
        }
        for n in nudges
    ]


@router.post("/{nudge_id}/respond")
async def respond_to_nudge(nudge_id: str, body: RespondRequest, db: AsyncClient = Depends(get_db), _user_id: str = Depends(get_current_user_id)):
    res = await db.table("nudge_logs").select("*").eq("id", nudge_id).limit(1).execute()

    open_chat = False
    chat_context = None

    if not res.data:
        return {"ok": True, "open_chat": open_chat, "chat_context": chat_context}

    nudge = res.data[0]
    now_iso = datetime.now(timezone.utc).isoformat()

    # Update nudge response
    await db.table("nudge_logs").update({
        "user_response": body.response,
        "responded_at": now_iso,
    }).eq("id", nudge_id).execute()

    await save_memory(
        db=db,
        content=f"User responded '{body.response}' to nudge: '{nudge['message']}'",
        memory_type=MemoryType.task_event,
        user_id=nudge["user_id"],
        task_id=nudge.get("task_id"),
        importance=0.65,
        ttl_hours=48,
    )

    action_type = infer_action_type(body.response)

    # Load task and related users for side effects
    task = None
    task_id = nudge.get("task_id")
    if task_id:
        task_res = await db.table("tasks").select("*").eq("id", task_id).limit(1).execute()
        task = task_res.data[0] if task_res.data else None

    responder_name = "Someone"
    if nudge.get("user_id"):
        user_res = await db.table("users").select("name").eq("id", nudge["user_id"]).limit(1).execute()
        if user_res.data:
            responder_name = user_res.data[0]["name"]

    if action_type == "done" and task:
        # Mark the task as done
        await db.table("tasks").update({
            "status": "done",
            "completed_at": now_iso,
            "updated_at": now_iso,
        }).eq("id", task["id"]).execute()

        # Save outcome learning: how long + how many nudges it took
        try:
            created_str = task.get("created_at", "")
            if created_str:
                created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                days_taken = (datetime.now(timezone.utc) - created_dt).days
                nudge_count = task.get("nudge_count", 0)
                await upsert_learning(
                    db=db,
                    user_id=nudge["user_id"],
                    content=f"Completed '{task['title']}' in {days_taken} day(s) after {nudge_count} nudge(s)",
                    importance=0.6,
                )
        except Exception:
            pass

        # Notify the owner if different from responder and connected
        if task.get("owner_id") and task["owner_id"] != nudge["user_id"]:
            if task["owner_id"] in ws_manager.connected_users:
                cross_nudge_id = str(uuid.uuid4())
                cross_msg = f"{responder_name} just finished '{task['title']}' ✓"
                await db.table("nudge_logs").insert({
                    "id": cross_nudge_id,
                    "user_id": task["owner_id"],
                    "task_id": task["id"],
                    "message": cross_msg,
                    "action_options": "Nice work!,Let's review",
                    "sent_at": now_iso,
                }).execute()
                await ws_manager.send_nudge(
                    user_id=task["owner_id"],
                    nudge_id=cross_nudge_id,
                    message=cross_msg,
                    action_options=["Nice work!", "Let's review"],
                    task_id=task["id"],
                )

    elif action_type == "help" and task:
        open_chat = True
        chat_context = f"I need help with: {task['title']}"
        # Notify the owner if different from responder and connected
        if task.get("owner_id") and task["owner_id"] != nudge["user_id"]:
            if task["owner_id"] in ws_manager.connected_users:
                cross_nudge_id = str(uuid.uuid4())
                cross_msg = f"{responder_name} is stuck on '{task['title']}' — they need help"
                await db.table("nudge_logs").insert({
                    "id": cross_nudge_id,
                    "user_id": task["owner_id"],
                    "task_id": task["id"],
                    "message": cross_msg,
                    "action_options": "I'm on it,Let's talk",
                    "sent_at": now_iso,
                }).execute()
                await ws_manager.send_nudge(
                    user_id=task["owner_id"],
                    nudge_id=cross_nudge_id,
                    message=cross_msg,
                    action_options=["I'm on it", "Let's talk"],
                    task_id=task["id"],
                )

    elif action_type == "chat" and task:
        open_chat = True
        chat_context = f"Let's talk about: {task['title']}"

    elif action_type == "remind_assignee" and task:
        # Ping the assignee if different from the nudge recipient and connected
        if task.get("assignee_id") and task["assignee_id"] != nudge["user_id"]:
            if task["assignee_id"] in ws_manager.connected_users:
                cross_nudge_id = str(uuid.uuid4())
                cross_msg = f"Quick check-in from {responder_name}: how's '{task['title']}' going?"
                await db.table("nudge_logs").insert({
                    "id": cross_nudge_id,
                    "user_id": task["assignee_id"],
                    "task_id": task["id"],
                    "message": cross_msg,
                    "action_options": "Making progress,Need help,Done!",
                    "sent_at": now_iso,
                }).execute()
                await ws_manager.send_nudge(
                    user_id=task["assignee_id"],
                    nudge_id=cross_nudge_id,
                    message=cross_msg,
                    action_options=["Making progress", "Need help", "Done!"],
                    task_id=task["id"],
                )

    elif action_type == "chat":
        open_chat = True

    # Snooze/ignore pattern: if this task has been dismissed 3+ times, learn from it
    if action_type in ("snooze", "ack") and task_id:
        try:
            history_res = await db.table("nudge_logs").select("user_response").eq(
                "task_id", task_id
            ).eq("user_id", nudge["user_id"]).execute()
            dismiss_count = sum(
                1 for n in (history_res.data or [])
                if n.get("user_response") and infer_action_type(n["user_response"]) in ("snooze", "ack")
            )
            if dismiss_count >= 3 and task:
                await upsert_learning(
                    db=db,
                    user_id=nudge["user_id"],
                    content=f"User has dismissed nudges about '{task['title']}' {dismiss_count} times — may need a different approach or task reconsideration",
                    importance=0.75,
                )
        except Exception:
            pass

    return {"ok": True, "open_chat": open_chat, "chat_context": chat_context}


@router.post("/{nudge_id}/dismiss")
async def dismiss_nudge(nudge_id: str, db: AsyncClient = Depends(get_db), _user_id: str = Depends(get_current_user_id)):
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.table("nudge_logs").update({
        "dismissed": True,
        "responded_at": now_iso,
    }).eq("id", nudge_id).execute()
    return {"ok": True}
