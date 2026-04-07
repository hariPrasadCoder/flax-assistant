from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from supabase import AsyncClient

from .database import get_db


async def get_current_user_id(
    authorization: str = Header(default=""),
    db: AsyncClient = Depends(get_db),
) -> str:
    """Verify Supabase JWT and return the authenticated user's ID."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization[len("Bearer "):].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        res = await db.auth.get_user(token)
        if not res.user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return res.user.id
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
