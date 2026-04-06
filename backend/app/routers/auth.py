from __future__ import annotations

from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, EmailStr
from typing import Optional
from passlib.context import CryptContext
from jose import jwt
import uuid

from ..database import get_db
from ..models import User, Team
from ..config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

pwd_context = CryptContext(schemes=["sha256_crypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_token(user_id: str) -> str:
    exp = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode({"sub": user_id, "exp": exp}, settings.secret_key, algorithm=settings.algorithm)


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    timezone: Optional[str] = "UTC"


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    user_id: str
    name: str
    email: str
    team_id: Optional[str]
    team_name: Optional[str]
    token: str


@router.post("/register", response_model=AuthResponse)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # Check email uniqueness
    result = await db.execute(select(User).where(User.email == data.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        id=str(uuid.uuid4()),
        name=data.name,
        email=data.email,
        hashed_password=hash_password(data.password),
        timezone=data.timezone or "UTC",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_token(user.id)
    return AuthResponse(
        user_id=user.id,
        name=user.name,
        email=user.email,
        team_id=None,
        team_name=None,
        token=token,
    )


@router.post("/login", response_model=AuthResponse)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    team_name = None
    if user.team_id:
        team_result = await db.execute(select(Team).where(Team.id == user.team_id))
        team = team_result.scalar_one_or_none()
        team_name = team.name if team else None

    token = create_token(user.id)
    return AuthResponse(
        user_id=user.id,
        name=user.name,
        email=user.email,
        team_id=user.team_id,
        team_name=team_name,
        token=token,
    )


class FocusRequest(BaseModel):
    user_id: str
    minutes: int


@router.post("/focus")
async def set_focus(data: FocusRequest, db: AsyncSession = Depends(get_db)):
    """Enable focus/DND mode for N minutes."""
    result = await db.execute(select(User).where(User.id == data.user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.focus_until = datetime.utcnow() + timedelta(minutes=data.minutes)
    await db.commit()
    return {"active": True, "until": user.focus_until.isoformat()}


@router.delete("/focus")
async def clear_focus(user_id: str, db: AsyncSession = Depends(get_db)):
    """Disable focus/DND mode."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.focus_until = None
    await db.commit()
    return {"active": False, "until": None}


@router.get("/focus")
async def get_focus(user_id: str, db: AsyncSession = Depends(get_db)):
    """Get current focus/DND status."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    now = datetime.utcnow()
    active = bool(user.focus_until and user.focus_until > now)
    return {
        "active": active,
        "until": user.focus_until.isoformat() if user.focus_until else None,
    }


@router.get("/me")
async def get_me(user_id: str, db: AsyncSession = Depends(get_db)):
    """Simple lookup by user_id (used by desktop on startup)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    team_name = None
    if user.team_id:
        team_result = await db.execute(select(Team).where(Team.id == user.team_id))
        team = team_result.scalar_one_or_none()
        team_name = team.name if team else None

    return {
        "user_id": user.id,
        "name": user.name,
        "email": user.email,
        "team_id": user.team_id,
        "team_name": team_name,
    }
