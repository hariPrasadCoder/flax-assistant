from __future__ import annotations

"""
WebSocket manager — maintains connections to desktop clients.
Pushes mascot state changes and nudges in real time.
"""

import json
import logging
from fastapi import WebSocket
from typing import Dict

logger = logging.getLogger(__name__)


class WebSocketManager:
    def __init__(self):
        # user_id → WebSocket (one active connection per user)
        self.connections: Dict[str, WebSocket] = {}

    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        self.connections[user_id] = websocket
        logger.info("[ws] %s connected (%d total)", user_id, len(self.connections))

    def disconnect(self, user_id: str):
        self.connections.pop(user_id, None)
        logger.info("[ws] %s disconnected", user_id)

    async def send_mascot_state(self, user_id: str, state: str):
        """Push a mascot state change to the desktop client."""
        await self._send(user_id, {"type": "mascot_state", "state": state})

    async def send_nudge(self, user_id: str, nudge_id: str, message: str, action_options: list[str], task_id: str | None = None):
        """Push a proactive nudge to the desktop client."""
        await self._send(user_id, {
            "type": "nudge",
            "id": nudge_id,
            "message": message,
            "action_options": action_options,
            "task_id": task_id,
        })

    async def send_reflection(self, user_id: str, message: str, mascot_state: str = "idle"):
        """Push a reflection insight as a chat message (not a notification)."""
        await self._send(user_id, {
            "type": "reflection",
            "message": message,
            "mascot_state": mascot_state,
        })

    async def broadcast_mascot_state(self, state: str):
        """Push a state update to all connected clients (e.g. local single-user mode)."""
        for user_id in list(self.connections.keys()):
            await self.send_mascot_state(user_id, state)

    async def _send(self, user_id: str, data: dict):
        ws = self.connections.get(user_id)
        if ws:
            try:
                await ws.send_text(json.dumps(data))
            except Exception as e:
                logger.error("[ws] send failed for %s: %s", user_id, e, exc_info=True)
                self.disconnect(user_id)

    @property
    def connected_users(self) -> list[str]:
        return list(self.connections.keys())


# Singleton
ws_manager = WebSocketManager()
