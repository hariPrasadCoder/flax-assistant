"""
Flax Assistant — FastAPI Backend
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from app.config import settings
from app.database import init_db
from app.scheduler import start_scheduler, stop_scheduler
from app.routers import tasks, chat, websocket, nudges, auth, team, calendar

# Configure logging early so all modules inherit the format
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Sentry — init before app creation so it catches startup errors too
if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        integrations=[
            StarletteIntegration(transaction_style="url"),
            FastApiIntegration(transaction_style="url"),
        ],
        traces_sample_rate=0.1,
        sample_rate=1.0,
    )
    logger.info("Sentry initialized (env=%s)", settings.app_env)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Flax Assistant backend starting (env=%s)", settings.app_env)
    await init_db()
    start_scheduler()
    logger.info("Flax Assistant backend running")
    yield
    # Shutdown
    stop_scheduler()


app = FastAPI(
    title="Flax Assistant API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — configurable via settings; defaults to * for local dev
origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
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
app.include_router(calendar.router)
app.include_router(websocket.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "flax-assistant", "env": settings.app_env}


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
