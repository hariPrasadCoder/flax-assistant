import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from ..database import AsyncSessionLocal
from ..models import User
from ..websocket_manager import ws_manager
from ..scheduler import register_user_for_nudges

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/mascot")
async def mascot_ws(websocket: WebSocket, user_id: str = "local"):
    # Accept immediately — never delay handshake
    await websocket.accept()

    resolved_id = user_id
    resolved_name = None

    # Single-user desktop mode: "local" → first registered user in DB
    if user_id == "local":
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(User).order_by(User.created_at.asc()).limit(1)
                )
                user_row = result.scalar_one_or_none()
                if user_row:
                    resolved_id = user_row.id
                    resolved_name = user_row.name
        except Exception as e:
            logger.error("[ws] user resolve error: %s", e, exc_info=True)

    # Store connection and start agent loop
    ws_manager.connections[resolved_id] = websocket
    logger.info("[ws] %s connected (resolved from '%s')", resolved_name or resolved_id, user_id)
    await register_user_for_nudges(resolved_id, resolved_name)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(resolved_id)
        logger.info("[ws] %s disconnected", resolved_name or resolved_id)
