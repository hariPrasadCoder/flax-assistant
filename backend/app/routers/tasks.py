from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from supabase import AsyncClient
from pydantic import BaseModel
from typing import Optional
import uuid

from ..database import get_db
from ..models import MemoryType
from ..ai.memory import save_memory

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    deadline: Optional[str] = None
    assignee_id: Optional[str] = None
    owner_id: Optional[str] = None
    team_id: Optional[str] = None
    is_team_visible: bool = True
    source: str = "chat"
    user_id: str  # the requesting user
    priority: Optional[int] = 3
    is_blocked: Optional[bool] = False


class TaskUpdate(BaseModel):
    status: Optional[str] = None
    deadline: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    assignee_id: Optional[str] = None
    priority: Optional[int] = None  # 1-5
    is_blocked: Optional[bool] = None
    blocked_reason: Optional[str] = None
    is_recurring: Optional[bool] = None
    recurrence_days: Optional[int] = None


class AssignRequest(BaseModel):
    assignee_id: str
    owner_id: str  # the user doing the assigning


class TaskResponse(BaseModel):
    id: str
    title: str
    description: Optional[str]
    status: str
    deadline: Optional[str]
    assignee_id: Optional[str]
    owner_id: Optional[str]
    nudge_count: int
    created_at: str
    source: str
    is_team_visible: bool

    class Config:
        from_attributes = True


@router.get("")
async def list_tasks(user_id: str, db: AsyncClient = Depends(get_db)):
    res = await (
        db.table("tasks")
        .select("*")
        .or_(f"assignee_id.eq.{user_id},owner_id.eq.{user_id}")
        .order("deadline", desc=False, nullsfirst=False)
        .order("created_at", desc=True)
        .execute()
    )
    tasks = res.data or []

    return [
        {
            "id": t["id"],
            "title": t["title"],
            "description": t.get("description"),
            "status": t["status"],
            "deadline": t.get("deadline"),
            "assignee_id": t.get("assignee_id"),
            "owner_id": t.get("owner_id"),
            "nudge_count": t.get("nudge_count", 0),
            "created_at": t["created_at"],
            "source": t.get("source", "chat"),
            "is_team_visible": t.get("is_team_visible", True),
            "priority": t.get("priority") if t.get("priority") is not None else 3,
            "is_blocked": t.get("is_blocked") or False,
            "blocked_reason": t.get("blocked_reason"),
            "is_recurring": t.get("is_recurring") or False,
            "recurrence_days": t.get("recurrence_days"),
        }
        for t in tasks
    ]


@router.post("")
async def create_task(data: TaskCreate, db: AsyncClient = Depends(get_db)):
    deadline = None
    if data.deadline:
        try:
            dt = datetime.fromisoformat(data.deadline.replace("Z", "+00:00"))
            deadline = dt.isoformat()
        except ValueError:
            pass

    task_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    task_dict = {
        "id": task_id,
        "title": data.title,
        "description": data.description,
        "deadline": deadline,
        "assignee_id": data.assignee_id or data.user_id,
        "owner_id": data.owner_id or data.user_id,
        "team_id": data.team_id,
        "source": data.source,
        "is_team_visible": data.is_team_visible,
        "priority": data.priority if data.priority is not None else 3,
        "is_blocked": data.is_blocked or False,
        "status": "open",
        "created_at": now_iso,
        "updated_at": now_iso,
        "nudge_count": 0,
    }
    res = await db.table("tasks").insert(task_dict).execute()
    task = res.data[0] if res.data else task_dict

    # Save as memory
    await save_memory(
        db=db,
        content=f"Task created: '{data.title}'" + (f" (due {data.deadline})" if data.deadline else ""),
        memory_type=MemoryType.task_event,
        user_id=data.user_id,
        task_id=task["id"],
        importance=0.7,
        ttl_hours=72,
    )

    return {
        "id": task["id"],
        "title": task["title"],
        "status": task["status"],
    }


@router.patch("/{task_id}")
async def update_task(task_id: str, data: TaskUpdate, db: AsyncClient = Depends(get_db)):
    # Fetch existing task
    res = await db.table("tasks").select("*").eq("id", task_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Task not found")

    patch: dict = {"updated_at": datetime.now(timezone.utc).isoformat()}

    if data.status is not None:
        patch["status"] = data.status
        if data.status == "done":
            patch["completed_at"] = datetime.now(timezone.utc).isoformat()

    if data.deadline is not None:
        try:
            dt = datetime.fromisoformat(data.deadline.replace("Z", "+00:00"))
            patch["deadline"] = dt.isoformat()
        except ValueError:
            pass

    if data.title is not None:
        patch["title"] = data.title

    if data.description is not None:
        patch["description"] = data.description

    if data.assignee_id is not None:
        patch["assignee_id"] = data.assignee_id

    if data.priority is not None:
        patch["priority"] = data.priority

    if data.is_blocked is not None:
        patch["is_blocked"] = data.is_blocked

    if data.blocked_reason is not None:
        patch["blocked_reason"] = data.blocked_reason

    if data.is_recurring is not None:
        patch["is_recurring"] = data.is_recurring

    if data.recurrence_days is not None:
        patch["recurrence_days"] = data.recurrence_days

    update_res = await db.table("tasks").update(patch).eq("id", task_id).execute()
    if not update_res.data:
        raise HTTPException(status_code=404, detail="Task not found")

    updated = update_res.data[0]
    return {"id": updated["id"], "status": updated["status"]}


@router.post("/{task_id}/assign")
async def assign_task(task_id: str, data: AssignRequest, db: AsyncClient = Depends(get_db)):
    res = await db.table("tasks").select("id").eq("id", task_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Task not found")

    patch = {
        "assignee_id": data.assignee_id,
        "owner_id": data.owner_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    update_res = await db.table("tasks").update(patch).eq("id", task_id).execute()
    updated = update_res.data[0] if update_res.data else {}
    return {
        "id": task_id,
        "assignee_id": updated.get("assignee_id", data.assignee_id),
        "owner_id": updated.get("owner_id", data.owner_id),
    }


@router.delete("/{task_id}")
async def delete_task(task_id: str, db: AsyncClient = Depends(get_db)):
    res = await db.table("tasks").select("id").eq("id", task_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Task not found")

    await db.table("tasks").delete().eq("id", task_id).execute()
    return {"ok": True}
