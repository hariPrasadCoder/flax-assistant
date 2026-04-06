"""
Flax Assistant — FastAPI Backend
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.scheduler import start_scheduler, stop_scheduler
from app.routers import tasks, chat, websocket, nudges, auth, team


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    start_scheduler()
    print("✦ Flax Assistant backend running")
    yield
    # Shutdown
    stop_scheduler()


app = FastAPI(
    title="Flax Assistant API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow Electron renderer and local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Lock down in production to your domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router)
app.include_router(tasks.router)
app.include_router(chat.router)
app.include_router(nudges.router)
app.include_router(team.router)
app.include_router(websocket.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "flax-assistant"}


@app.post("/api/debug/nudge")
async def debug_nudge(user_id: str = "any", message: str = "Hey! Just checking in — how are your tasks going?"):
    """Dev-only: send a test notification. user_id='any' sends to first connected user."""
    import uuid
    from app.websocket_manager import ws_manager
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models import User

    nudge_id = str(uuid.uuid4())

    # Resolve target: use first connected user if "any" or "local"
    target_id = user_id
    if user_id in ("any", "local") or not ws_manager.connections.get(user_id):
        if ws_manager.connections:
            target_id = list(ws_manager.connections.keys())[0]
        else:
            # Try first DB user as fallback
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(User).order_by(User.created_at.asc()).limit(1))
                u = result.scalar_one_or_none()
                if u:
                    target_id = u.id

    await ws_manager.send_nudge(
        user_id=target_id,
        nudge_id=nudge_id,
        message=message,
        action_options=["On it!", "Let's talk", "Snooze 1h"],
        task_id=None,
    )
    connected = list(ws_manager.connections.keys())
    return {"sent": True, "nudge_id": nudge_id, "to": target_id, "connected_users": connected}
