import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from ..config import settings
from ..database import get_db
from ..websocket_manager import ws_manager
from ..scheduler import register_user_for_nudges

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/mascot")
async def mascot_ws(websocket: WebSocket, user_id: str = "local"):
    # In production, reject unauthenticated connections
    if user_id == "local" and settings.app_env == "production":
        await websocket.close(code=4001, reason="Authentication required")
        return

    # Accept immediately — never delay handshake
    await websocket.accept()

    resolved_id = user_id
    resolved_name = None

    # Dev-mode only: "local" → first registered user in DB
    if user_id == "local":
        try:
            db = await get_db()
            res = await db.table("users").select("id, name").order("created_at").limit(1).execute()
            if res.data:
                resolved_id = res.data[0]["id"]
                resolved_name = res.data[0]["name"]
        except Exception as e:
            logger.error("[ws] user resolve error: %s", e, exc_info=True)

    # Resolve name for known users
    if resolved_name is None and resolved_id != "local":
        try:
            db = await get_db()
            res = await db.table("users").select("name").eq("id", resolved_id).limit(1).execute()
            if res.data:
                resolved_name = res.data[0]["name"]
        except Exception:
            pass

    ws_manager.connections[resolved_id] = websocket
    logger.info("[ws] %s connected (resolved from '%s')", resolved_name or resolved_id, user_id)
    await register_user_for_nudges(resolved_id, resolved_name)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(resolved_id)
        logger.info("[ws] %s disconnected", resolved_name or resolved_id)
