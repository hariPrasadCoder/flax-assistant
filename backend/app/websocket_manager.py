from __future__ import annotations

"""
WebSocket manager — maintains connections to desktop clients.
Pushes mascot state changes and nudges in real time.
"""

import json
from fastapi import WebSocket
from typing import Dict


class WebSocketManager:
    def __init__(self):
        # user_id → WebSocket (one active connection per user)
        self.connections: Dict[str, WebSocket] = {}

    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        self.connections[user_id] = websocket
        print(f"[ws] {user_id} connected ({len(self.connections)} total)")

    def disconnect(self, user_id: str):
        self.connections.pop(user_id, None)
        print(f"[ws] {user_id} disconnected")

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

    async def broadcast_mascot_state(self, state: str):
        """Push a state update to all connected clients (e.g. local single-user mode)."""
        for user_id in list(self.connections.keys()):
            await self.send_mascot_state(user_id, state)

    async def _send(self, user_id: str, data: dict):
        ws = self.connections.get(user_id)
        if ws:
            try:
                await ws.send_text(json.dumps(data))
            except Exception:
                self.disconnect(user_id)

    @property
    def connected_users(self) -> list[str]:
        return list(self.connections.keys())


# Singleton
ws_manager = WebSocketManager()
