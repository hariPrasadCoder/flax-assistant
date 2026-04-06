from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional

from ..database import get_db
from ..models import User, Team, Task, TaskStatus, InviteCode

router = APIRouter(prefix="/api/team", tags=["team"])


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
    await db.flush()

    # Generate DB-backed invite code
    code = secrets.token_urlsafe(6).upper()[:8]
    invite = InviteCode(
        code=code,
        team_id=team.id,
        expires_at=datetime.utcnow() + timedelta(days=7),
    )
    db.add(invite)
    await db.commit()

    return {
        "team_id": team.id,
        "team_name": team.name,
        "invite_code": code,
    }


@router.post("/join")
async def join_team(data: JoinTeamRequest, db: AsyncSession = Depends(get_db)):
    now = datetime.utcnow()

    invite_result = await db.execute(select(InviteCode).where(InviteCode.code == data.invite_code))
    invite = invite_result.scalar_one_or_none()

    if not invite:
        raise HTTPException(status_code=404, detail="Invalid invite code")
    if invite.used:
        raise HTTPException(status_code=400, detail="Invite code already used")
    if invite.expires_at and invite.expires_at < now:
        raise HTTPException(status_code=400, detail="Invite code expired")

    result = await db.execute(select(User).where(User.id == data.user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    team_result = await db.execute(select(Team).where(Team.id == invite.team_id))
    team = team_result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    user.team_id = invite.team_id
    invite.used = True
    await db.commit()

    return {"team_id": invite.team_id, "team_name": team.name}


@router.get("/generate-invite")
async def generate_invite(team_id: str, db: AsyncSession = Depends(get_db)):
    code = secrets.token_urlsafe(6).upper()[:8]
    invite = InviteCode(
        code=code,
        team_id=team_id,
        expires_at=datetime.utcnow() + timedelta(days=7),
    )
    db.add(invite)
    await db.commit()
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
