from __future__ import annotations

import uuid
import random
import string
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional

from ..database import get_db
from ..models import User, Team, Task, TaskStatus

router = APIRouter(prefix="/api/team", tags=["team"])

# Simple in-memory invite codes (in production: store in DB with TTL)
_invite_codes: dict[str, str] = {}  # code → team_id


def generate_invite_code() -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


class CreateTeamRequest(BaseModel):
    name: str
    user_id: str


class JoinTeamRequest(BaseModel):
    invite_code: str
    user_id: str


@router.post("/create")
async def create_team(data: CreateTeamRequest, db: AsyncSession = Depends(get_db)):
    team = Team(id=str(uuid.uuid4()), name=data.name)
    db.add(team)

    # Assign user to team
    result = await db.execute(select(User).where(User.id == data.user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.team_id = team.id
    await db.commit()

    # Generate invite code
    code = generate_invite_code()
    _invite_codes[code] = team.id

    return {
        "team_id": team.id,
        "team_name": team.name,
        "invite_code": code,
    }


@router.post("/join")
async def join_team(data: JoinTeamRequest, db: AsyncSession = Depends(get_db)):
    team_id = _invite_codes.get(data.invite_code)
    if not team_id:
        raise HTTPException(status_code=404, detail="Invalid invite code")

    result = await db.execute(select(User).where(User.id == data.user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    team_result = await db.execute(select(Team).where(Team.id == team_id))
    team = team_result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    user.team_id = team_id
    await db.commit()

    return {"team_id": team_id, "team_name": team.name}


@router.get("/generate-invite")
async def generate_invite(team_id: str):
    code = generate_invite_code()
    _invite_codes[code] = team_id
    return {"invite_code": code}


@router.get("/overview")
async def team_overview(team_id: str, db: AsyncSession = Depends(get_db)):
    """Team dashboard: who's working on what."""
    # Get all team members
    members_result = await db.execute(
        select(User).where(User.team_id == team_id)
    )
    members = members_result.scalars().all()

    # Get all open team tasks
    tasks_result = await db.execute(
        select(Task).where(
            Task.team_id == team_id,
            Task.status != TaskStatus.done,
            Task.is_team_visible == True,
        )
        .order_by(Task.deadline.asc().nullslast())
    )
    tasks = tasks_result.scalars().all()

    # Build per-member task map
    member_map = {m.id: {"name": m.name, "tasks": []} for m in members}

    for t in tasks:
        assignee_id = t.assignee_id
        if assignee_id and assignee_id in member_map:
            member_map[assignee_id]["tasks"].append({
                "id": t.id,
                "title": t.title,
                "status": t.status.value,
                "deadline": t.deadline.isoformat() if t.deadline else None,
                "nudge_count": t.nudge_count,
            })

    return {
        "team_id": team_id,
        "members": [
            {
                "user_id": uid,
                "name": info["name"],
                "open_tasks": len(info["tasks"]),
                "tasks": info["tasks"],
            }
            for uid, info in member_map.items()
        ],
        "total_open_tasks": len(tasks),
    }
