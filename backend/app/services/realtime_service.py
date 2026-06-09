from __future__ import annotations

from typing import Any

from app.core.ws_manager import ws_manager


def _safe_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """
    Keep realtime payloads lightweight and JSON-friendly.

    The frontend should receive only short metadata and then refresh full state
    through existing REST endpoints.
    """
    return payload or {}


async def broadcast_realtime_event(
    event_type: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """
    Async realtime broadcast.

    Use this from async endpoints or async workers when the event loop is already available.
    """
    await ws_manager.broadcast(
        event_type=event_type,
        message=message,
        payload=_safe_payload(payload),
    )


def emit_realtime_event(
    event_type: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """
    Fire-and-forget realtime event from synchronous service code.

    The current backend services are mostly synchronous and often run inside
    FastAPI's worker threadpool. The WebSocket manager schedules the broadcast
    on the WebSocket event loop captured during connection.
    """
    ws_manager.broadcast_from_sync(
        event_type=event_type,
        message=message,
        payload=_safe_payload(payload),
    )


def emit_workspace_updated(
    event_type: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """
    Convenience helper for UI-refresh events.

    The frontend treats these events as a signal to reload files, audit, flows,
    security findings, graph and compliance data.
    """
    emit_realtime_event(
        event_type=event_type,
        message=message,
        payload={
            "workspace_updated": True,
            **_safe_payload(payload),
        },
    )


def realtime_connection_count() -> int:
    return ws_manager.connection_count()