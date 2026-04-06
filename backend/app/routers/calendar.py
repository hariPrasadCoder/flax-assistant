from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)

from ..database import get_db
from ..models import User
from ..config import settings

router = APIRouter(prefix="/api/calendar", tags=["calendar"])

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
REDIRECT_URI = "http://localhost:8747/api/calendar/callback"


def get_flow():
    return Flow.from_client_config(
        {
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uris": [REDIRECT_URI],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )


@router.get("/connect")
async def connect_calendar(user_id: str):
    """Start Google Calendar OAuth flow."""
    flow = get_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        state=user_id,
        prompt="consent",
    )
    return RedirectResponse(auth_url)


@router.get("/callback")
async def calendar_callback(code: str, state: str, db: AsyncSession = Depends(get_db)):
    """Handle OAuth callback, store tokens."""
    user_id = state
    flow = get_flow()
    flow.fetch_token(code=code)
    creds = flow.credentials
    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or SCOPES),
    }
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.google_calendar_token = json.dumps(token_data)
    await db.commit()
    # Redirect back to app
    return RedirectResponse("http://localhost:5173/chat.html?calendar=connected")


@router.get("/events")
async def get_today_events(user_id: str, db: AsyncSession = Depends(get_db)):
    """Get today's calendar events for context injection."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.google_calendar_token:
        return {"events": [], "connected": False}
    try:
        token_data = json.loads(user.google_calendar_token)
        creds = Credentials(
            token=token_data["token"],
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data["token_uri"],
            client_id=token_data["client_id"],
            client_secret=token_data["client_secret"],
            scopes=token_data.get("scopes", SCOPES),
        )
        service = build("calendar", "v3", credentials=creds)
        now = datetime.now(timezone.utc)
        end_of_day = now.replace(hour=23, minute=59, second=59)
        events_result = service.events().list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=end_of_day.isoformat(),
            maxResults=10,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = []
        for e in events_result.get("items", []):
            start = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date")
            end = e.get("end", {}).get("dateTime") or e.get("end", {}).get("date")
            events.append({"title": e.get("summary", "Meeting"), "start": start, "end": end})
        return {"events": events, "connected": True}
    except Exception as ex:
        logger.error("[calendar] error fetching events for %s: %s", user_id, ex, exc_info=True)
        return {"events": [], "connected": True, "error": str(ex)}


@router.delete("/disconnect")
async def disconnect_calendar(user_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        user.google_calendar_token = None
        await db.commit()
    return {"ok": True}
