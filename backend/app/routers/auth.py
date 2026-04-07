from __future__ import annotations

from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from supabase import AsyncClient
from pydantic import BaseModel, EmailStr
from typing import Optional

from ..database import get_db
from ..deps import get_current_user_id

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SetupRequest(BaseModel):
    """Called once after OTP verification to create/update the user's profile."""
    user_id: Optional[str] = None  # ignored — user_id comes from auth token
    name: str
    email: EmailStr
    timezone: Optional[str] = "UTC"


class SetupResponse(BaseModel):
    user_id: str
    name: str
    email: str
    team_id: Optional[str]
    team_name: Optional[str]


@router.post("/setup", response_model=SetupResponse)
async def setup_user(data: SetupRequest, db: AsyncClient = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    """
    Create or update the user profile row after successful OTP verification.
    Idempotent — safe to call on every login (updating name / timezone).
    """
    if not data.name.strip():
        raise HTTPException(status_code=400, detail="Name cannot be empty")

    user_dict = {
        "id": user_id,
        "name": data.name.strip(),
        "email": data.email,
        "timezone": data.timezone or "UTC",
    }
    res = await db.table("users").upsert(user_dict, on_conflict="id").execute()
    user = res.data[0] if res.data else user_dict

    team_name = None
    if user.get("team_id"):
        team_res = await db.table("teams").select("name").eq("id", user["team_id"]).limit(1).execute()
        if team_res.data:
            team_name = team_res.data[0]["name"]

    return SetupResponse(
        user_id=user["id"],
        name=user["name"],
        email=user["email"],
        team_id=user.get("team_id"),
        team_name=team_name,
    )


@router.get("/me")
async def get_me(user_id: str = Depends(get_current_user_id), db: AsyncClient = Depends(get_db)):
    """Look up user profile — used by desktop on startup to check if setup is needed."""
    res = await db.table("users").select("*").eq("id", user_id).limit(1).execute()
    if not res.data:
        return None  # 200 with null = new user, needs setup

    user = res.data[0]
    team_name = None
    if user.get("team_id"):
        team_res = await db.table("teams").select("name").eq("id", user["team_id"]).limit(1).execute()
        if team_res.data:
            team_name = team_res.data[0]["name"]

    return {
        "user_id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "team_id": user.get("team_id"),
        "team_name": team_name,
    }


class FocusRequest(BaseModel):
    user_id: Optional[str] = None  # ignored — user_id comes from auth token
    minutes: int


@router.post("/focus")
async def set_focus(data: FocusRequest, db: AsyncClient = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    """Enable focus/DND mode for N minutes."""
    focus_until = (datetime.now(timezone.utc) + timedelta(minutes=data.minutes)).isoformat()
    await db.table("users").update({"focus_until": focus_until}).eq("id", user_id).execute()
    return {"active": True, "until": focus_until}


@router.delete("/focus")
async def clear_focus(user_id: str = Depends(get_current_user_id), db: AsyncClient = Depends(get_db)):
    """Disable focus/DND mode."""
    await db.table("users").update({"focus_until": None}).eq("id", user_id).execute()
    return {"active": False, "until": None}


@router.get("/focus")
async def get_focus(user_id: str = Depends(get_current_user_id), db: AsyncClient = Depends(get_db)):
    """Get current focus/DND status."""
    res = await db.table("users").select("focus_until").eq("id", user_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="User not found")

    focus_until_str = res.data[0].get("focus_until")
    now = datetime.now(timezone.utc)
    active = False
    if focus_until_str:
        try:
            dt = datetime.fromisoformat(focus_until_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            active = dt > now
        except ValueError:
            pass

    return {"active": active, "until": focus_until_str if active else None}
