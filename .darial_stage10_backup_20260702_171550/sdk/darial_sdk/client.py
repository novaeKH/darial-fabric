from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib import request


@dataclass
class DarialClient:
    base_url: str
    api_key: str
    timeout: int = 10
    _buffer: list[dict[str, Any]] = field(default_factory=list)

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.base_url.rstrip('/')}{path}",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        with request.urlopen(req, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def track_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        event_id: str | None = None,
        product_id: str | None = None,
        agent_name: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        event = {
            "event_id": event_id or str(uuid.uuid4()),
            "event_type": event_type,
            "product_id": product_id,
            "agent_name": agent_name,
            "trace_id": trace_id,
            "payload": payload,
        }
        return self._post("/api/ingestion/events", event)

    def track_run(
        self,
        *,
        event_id: str | None = None,
        agent_name: str,
        trace_id: str,
        payload: dict[str, Any],
        product_id: str | None = None,
    ) -> dict[str, Any]:
        return self.track_event(
            "agent_run",
            payload,
            event_id=event_id,
            product_id=product_id,
            agent_name=agent_name,
            trace_id=trace_id,
        )

    def add_to_batch(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        event_id: str | None = None,
        product_id: str | None = None,
        agent_name: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        self._buffer.append({
            "event_id": event_id or str(uuid.uuid4()),
            "event_type": event_type,
            "product_id": product_id,
            "agent_name": agent_name,
            "trace_id": trace_id,
            "payload": payload,
        })

    def flush(self) -> dict[str, Any]:
        if not self._buffer:
            return {"accepted": 0, "duplicate": 0}
        events = self._buffer
        self._buffer = []
        return self._post("/api/ingestion/events/batch", {"events": events})
