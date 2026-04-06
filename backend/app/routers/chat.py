from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional, List

from ..database import get_db
from ..models import Task, TaskStatus, MemoryType, ChatMessage, NudgeLog
from ..ai.brain import chat as ai_chat
from ..ai.agent import agent_greeting
from ..ai.memory import get_recent_memories, get_learnings, save_memory, upsert_learning
from ..websocket_manager import ws_manager
import uuid

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    user_id: str
    user_name: Optional[str] = None
    history: list[dict] = []



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

    # Call AI
    ai_result = await ai_chat(
        user_message=req.message,
        history=req.history,
        tasks=tasks_data,
        memories=memories,
        learnings=learnings,
        recent_nudges=recent_nudges,
        user_name=req.user_name,
    )

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
