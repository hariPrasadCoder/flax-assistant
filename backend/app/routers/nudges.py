import uuid
from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from ..database import get_db
from ..models import NudgeLog, Task, TaskStatus, User
from ..ai.memory import save_memory
from ..models import MemoryType
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
async def get_nudge_history(user_id: str, limit: int = 20, db: AsyncSession = Depends(get_db)):
    """Return the last N nudges for a user."""
    result = await db.execute(
        select(NudgeLog)
        .where(NudgeLog.user_id == user_id)
        .order_by(NudgeLog.sent_at.desc())
        .limit(limit)
    )
    nudges = result.scalars().all()
    return [
        {
            "id": n.id,
            "message": n.message,
            "sent_at": n.sent_at.isoformat(),
            "user_response": n.user_response,
            "responded_at": n.responded_at.isoformat() if n.responded_at else None,
            "dismissed": n.dismissed,
            "task_id": n.task_id,
        }
        for n in nudges
    ]


@router.post("/{nudge_id}/respond")
async def respond_to_nudge(nudge_id: str, body: RespondRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NudgeLog).where(NudgeLog.id == nudge_id))
    nudge = result.scalar_one_or_none()

    open_chat = False
    chat_context = None

    if nudge:
        nudge.user_response = body.response
        nudge.responded_at = datetime.utcnow()

        await save_memory(
            db=db,
            content=f"User responded '{body.response}' to nudge: '{nudge.message}'",
            memory_type=MemoryType.task_event,
            user_id=nudge.user_id,
            task_id=nudge.task_id,
            importance=0.65,
            ttl_hours=48,
        )

        action_type = infer_action_type(body.response)

        # Load task and related users for side effects
        task = None
        if nudge.task_id:
            task_result = await db.execute(select(Task).where(Task.id == nudge.task_id))
            task = task_result.scalar_one_or_none()

        responder_name = "Someone"
        if nudge.user_id:
            user_result = await db.execute(select(User).where(User.id == nudge.user_id))
            responder_user = user_result.scalar_one_or_none()
            if responder_user:
                responder_name = responder_user.name

        if action_type == "done" and task:
            # Mark the task as done
            task.status = TaskStatus.done
            task.completed_at = datetime.utcnow()
            task.updated_at = datetime.utcnow()

            # Notify the owner if different from responder and connected
            if task.owner_id and task.owner_id != nudge.user_id:
                if task.owner_id in ws_manager.connected_users:
                    cross_nudge_id = str(uuid.uuid4())
                    cross_log = NudgeLog(
                        id=cross_nudge_id,
                        user_id=task.owner_id,
                        task_id=task.id,
                        message=f"{responder_name} just finished '{task.title}' ✓",
                        action_options="Nice work!,Let's review",
                    )
                    db.add(cross_log)
                    await ws_manager.send_nudge(
                        user_id=task.owner_id,
                        nudge_id=cross_nudge_id,
                        message=f"{responder_name} just finished '{task.title}' ✓",
                        action_options=["Nice work!", "Let's review"],
                        task_id=task.id,
                    )

        elif action_type == "help" and task:
            open_chat = True
            chat_context = f"I need help with: {task.title}"
            # Notify the owner if different from responder and connected
            if task.owner_id and task.owner_id != nudge.user_id:
                if task.owner_id in ws_manager.connected_users:
                    cross_nudge_id = str(uuid.uuid4())
                    cross_log = NudgeLog(
                        id=cross_nudge_id,
                        user_id=task.owner_id,
                        task_id=task.id,
                        message=f"{responder_name} is stuck on '{task.title}' — they need help",
                        action_options="I'm on it,Let's talk",
                    )
                    db.add(cross_log)
                    await ws_manager.send_nudge(
                        user_id=task.owner_id,
                        nudge_id=cross_nudge_id,
                        message=f"{responder_name} is stuck on '{task.title}' — they need help",
                        action_options=["I'm on it", "Let's talk"],
                        task_id=task.id,
                    )

        elif action_type == "chat" and task:
            open_chat = True
            chat_context = f"Let's talk about: {task.title}"

        elif action_type == "remind_assignee" and task:
            # Ping the assignee if different from the nudge recipient and connected
            if task.assignee_id and task.assignee_id != nudge.user_id:
                if task.assignee_id in ws_manager.connected_users:
                    cross_nudge_id = str(uuid.uuid4())
                    cross_log = NudgeLog(
                        id=cross_nudge_id,
                        user_id=task.assignee_id,
                        task_id=task.id,
                        message=f"Quick check-in from {responder_name}: how's '{task.title}' going?",
                        action_options="Making progress,Need help,Done!",
                    )
                    db.add(cross_log)
                    await ws_manager.send_nudge(
                        user_id=task.assignee_id,
                        nudge_id=cross_nudge_id,
                        message=f"Quick check-in from {responder_name}: how's '{task.title}' going?",
                        action_options=["Making progress", "Need help", "Done!"],
                        task_id=task.id,
                    )

        elif action_type == "chat":
            open_chat = True

        await db.commit()

    return {"ok": True, "open_chat": open_chat, "chat_context": chat_context}


@router.post("/{nudge_id}/dismiss")
async def dismiss_nudge(nudge_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NudgeLog).where(NudgeLog.id == nudge_id))
    nudge = result.scalar_one_or_none()

    if nudge:
        nudge.dismissed = True
        nudge.responded_at = datetime.utcnow()
        await db.commit()

    return {"ok": True}
