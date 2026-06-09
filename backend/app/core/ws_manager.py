from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketState


logger = logging.getLogger(__name__)

class WebSocketManager:
    """
    Small in-memory WebSocket connection manager for local demo and MVP realtime updates.

    This manager is intentionally simple:
    - keeps active frontend connections in memory;
    - broadcasts lightweight events;
    - frontend receives an event and reloads data through regular REST endpoints.

    In production this can be replaced with Redis Pub/Sub, NATS, Kafka, or another event bus.
    """

    def __init__(self) -> None:
        self.active_connections: set[WebSocket] = set()
        self._event_loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._event_loop = asyncio.get_running_loop()
        self.active_connections.add(websocket)
        await self.send_personal_message(
            websocket,
            event_type="realtime_connected",
            message="Realtime WebSocket connected",
            payload={
                "connections": len(self.active_connections),
            },
        )

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.discard(websocket)

    async def send_personal_message(
        self,
        websocket: WebSocket,
        event_type: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if websocket.client_state != WebSocketState.CONNECTED:
            self.disconnect(websocket)
            return

        await websocket.send_json(
            self._event_message(
                event_type=event_type,
                message=message,
                payload=payload,
            )
        )

    async def broadcast(
        self,
        event_type: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if not self.active_connections:
            return

        event = self._event_message(
            event_type=event_type,
            message=message,
            payload=payload,
        )

        disconnected: list[WebSocket] = []

        for connection in list(self.active_connections):
            if connection.client_state != WebSocketState.CONNECTED:
                disconnected.append(connection)
                continue

            try:
                await connection.send_json(event)
            except Exception:
                disconnected.append(connection)

        for connection in disconnected:
            self.disconnect(connection)

    def broadcast_from_sync(
        self,
        event_type: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """
        Thread-safe broadcast helper for synchronous service code.

        FastAPI runs regular def endpoints and service calls in a worker thread.
        Such code usually has no running asyncio event loop, so direct
        asyncio.get_running_loop().create_task(...) silently cannot work there.

        This method schedules broadcast(...) on the event loop captured from the
        active WebSocket connection.
        """
        if not self.active_connections:
            return

        if self._event_loop is None or self._event_loop.is_closed():
            logger.debug("Realtime event skipped because WebSocket event loop is not available: %s", event_type)
            return

        try:
            asyncio.run_coroutine_threadsafe(
                self.broadcast(
                    event_type=event_type,
                    message=message,
                    payload=payload,
                ),
                self._event_loop,
            )
        except Exception:
            logger.exception("Failed to schedule realtime WebSocket event: %s", event_type)

    def connection_count(self) -> int:
        return len(self.active_connections)

    @staticmethod
    def _event_message(
        event_type: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "type": event_type,
            "message": message,
            "payload": payload or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }


ws_manager = WebSocketManager()