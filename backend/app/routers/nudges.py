from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from ..database import get_db
from ..models import NudgeLog
from ..ai.memory import save_memory
from ..models import MemoryType

router = APIRouter(prefix="/api/nudges", tags=["nudges"])


class RespondRequest(BaseModel):
    response: str


@router.post("/{nudge_id}/respond")
async def respond_to_nudge(nudge_id: str, body: RespondRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NudgeLog).where(NudgeLog.id == nudge_id))
    nudge = result.scalar_one_or_none()

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
        await db.commit()

    return {"ok": True}


@router.post("/{nudge_id}/dismiss")
async def dismiss_nudge(nudge_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NudgeLog).where(NudgeLog.id == nudge_id))
    nudge = result.scalar_one_or_none()

    if nudge:
        nudge.dismissed = True
        nudge.responded_at = datetime.utcnow()
        await db.commit()

    return {"ok": True}
