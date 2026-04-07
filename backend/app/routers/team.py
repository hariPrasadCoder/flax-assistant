from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from supabase import AsyncClient
from pydantic import BaseModel
from typing import Optional

from ..database import get_db

router = APIRouter(prefix="/api/team", tags=["team"])


class CreateTeamRequest(BaseModel):
    name: str
    user_id: str


class JoinTeamRequest(BaseModel):
    invite_code: str
    user_id: str


@router.post("/create")
async def create_team(data: CreateTeamRequest, db: AsyncClient = Depends(get_db)):
    team_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    # Create team
    await db.table("teams").insert({
        "id": team_id,
        "name": data.name,
        "created_at": now_iso,
    }).execute()

    # Verify user exists
    user_res = await db.table("users").select("id").eq("id", data.user_id).limit(1).execute()
    if not user_res.data:
        raise HTTPException(status_code=404, detail="User not found")

    # Assign user to team
    await db.table("users").update({"team_id": team_id}).eq("id", data.user_id).execute()

    # Generate DB-backed invite code
    code = secrets.token_urlsafe(6).upper()[:8]
    expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    await db.table("invite_codes").insert({
        "code": code,
        "team_id": team_id,
        "created_at": now_iso,
        "expires_at": expires_at,
        "used": False,
    }).execute()

    return {
        "team_id": team_id,
        "team_name": data.name,
        "invite_code": code,
    }


@router.post("/join")
async def join_team(data: JoinTeamRequest, db: AsyncClient = Depends(get_db)):
    now_iso = datetime.now(timezone.utc).isoformat()
    now = datetime.now(timezone.utc)

    invite_res = await db.table("invite_codes").select("*").eq("code", data.invite_code).limit(1).execute()
    if not invite_res.data:
        raise HTTPException(status_code=404, detail="Invalid invite code")

    invite = invite_res.data[0]

    if invite.get("used"):
        raise HTTPException(status_code=400, detail="Invite code already used")

    if invite.get("expires_at"):
        try:
            exp = datetime.fromisoformat(invite["expires_at"].replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < now:
                raise HTTPException(status_code=400, detail="Invite code expired")
        except HTTPException:
            raise
        except Exception:
            pass

    user_res = await db.table("users").select("id").eq("id", data.user_id).limit(1).execute()
    if not user_res.data:
        raise HTTPException(status_code=404, detail="User not found")

    team_res = await db.table("teams").select("name").eq("id", invite["team_id"]).limit(1).execute()
    if not team_res.data:
        raise HTTPException(status_code=404, detail="Team not found")

    team_name = team_res.data[0]["name"]

    # Assign user to team and mark invite used
    await db.table("users").update({"team_id": invite["team_id"]}).eq("id", data.user_id).execute()
    await db.table("invite_codes").update({"used": True}).eq("code", data.invite_code).execute()

    return {"team_id": invite["team_id"], "team_name": team_name}


@router.get("/generate-invite")
async def generate_invite(team_id: str, db: AsyncClient = Depends(get_db)):
    code = secrets.token_urlsafe(6).upper()[:8]
    now_iso = datetime.now(timezone.utc).isoformat()
    expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    await db.table("invite_codes").insert({
        "code": code,
        "team_id": team_id,
        "created_at": now_iso,
        "expires_at": expires_at,
        "used": False,
    }).execute()
    return {"invite_code": code}


@router.get("/overview")
async def team_overview(team_id: str, db: AsyncClient = Depends(get_db)):
    """Team dashboard: who's working on what."""
    # Get all team members
    members_res = await db.table("users").select("id, name").eq("team_id", team_id).execute()
    members = members_res.data or []

    # Get all open team tasks
    tasks_res = await (
        db.table("tasks")
        .select("*")
        .eq("team_id", team_id)
        .neq("status", "done")
        .eq("is_team_visible", True)
        .order("deadline", desc=False, nullsfirst=False)
        .execute()
    )
    tasks = tasks_res.data or []

    # Build per-member task map
    member_map = {m["id"]: {"name": m["name"], "tasks": []} for m in members}

    for t in tasks:
        assignee_id = t.get("assignee_id")
        if assignee_id and assignee_id in member_map:
            member_map[assignee_id]["tasks"].append({
                "id": t["id"],
                "title": t["title"],
                "status": t["status"],
                "deadline": t.get("deadline"),
                "nudge_count": t.get("nudge_count", 0),
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
