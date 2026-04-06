from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional

from ..database import get_db
from ..models import Task, TaskStatus, Memory, MemoryType
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


class TaskUpdate(BaseModel):
    status: Optional[str] = None
    deadline: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    assignee_id: Optional[str] = None


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
async def list_tasks(user_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Task)
        .where(
            (Task.assignee_id == user_id) | (Task.owner_id == user_id)
        )
        .order_by(Task.deadline.asc().nullslast(), Task.created_at.desc())
    )
    tasks = result.scalars().all()

    return [
        {
            "id": t.id,
            "title": t.title,
            "description": t.description,
            "status": t.status.value,
            "deadline": t.deadline.isoformat() if t.deadline else None,
            "assignee_id": t.assignee_id,
            "owner_id": t.owner_id,
            "nudge_count": t.nudge_count,
            "created_at": t.created_at.isoformat(),
            "source": t.source,
            "is_team_visible": t.is_team_visible,
        }
        for t in tasks
    ]


@router.post("")
async def create_task(data: TaskCreate, db: AsyncSession = Depends(get_db)):
    deadline = None
    if data.deadline:
        try:
            deadline = datetime.fromisoformat(data.deadline.replace("Z", "+00:00"))
        except ValueError:
            pass

    task = Task(
        title=data.title,
        description=data.description,
        deadline=deadline,
        assignee_id=data.assignee_id or data.user_id,
        owner_id=data.owner_id or data.user_id,
        team_id=data.team_id,
        source=data.source,
        is_team_visible=data.is_team_visible,
    )
    db.add(task)
    await db.flush()

    # Save as memory
    await save_memory(
        db=db,
        content=f"Task created: '{data.title}'" + (f" (due {data.deadline})" if data.deadline else ""),
        memory_type=MemoryType.task_event,
        user_id=data.user_id,
        task_id=task.id,
        importance=0.7,
        ttl_hours=72,
    )

    return {
        "id": task.id,
        "title": task.title,
        "status": task.status.value,
    }


@router.patch("/{task_id}")
async def update_task(task_id: str, data: TaskUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if data.status:
        task.status = TaskStatus(data.status)
        if data.status == "done":
            task.completed_at = datetime.utcnow()

    if data.deadline:
        try:
            task.deadline = datetime.fromisoformat(data.deadline.replace("Z", "+00:00"))
        except ValueError:
            pass

    if data.title:
        task.title = data.title

    if data.description is not None:
        task.description = data.description

    if data.assignee_id is not None:
        task.assignee_id = data.assignee_id

    task.updated_at = datetime.utcnow()
    await db.commit()
    return {"id": task.id, "status": task.status.value}


@router.post("/{task_id}/assign")
async def assign_task(task_id: str, data: AssignRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.assignee_id = data.assignee_id
    task.owner_id = data.owner_id
    task.updated_at = datetime.utcnow()
    await db.commit()
    return {"id": task.id, "assignee_id": task.assignee_id, "owner_id": task.owner_id}


@router.delete("/{task_id}")
async def delete_task(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    await db.delete(task)
    await db.commit()
    return {"ok": True}
