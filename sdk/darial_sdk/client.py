from __future__ import annotations

import json
import os
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any
from urllib import error, request

SENSITIVE_KEYS = {
    "authorization", "api_key", "apikey", "access_token",
    "refresh_token", "password", "passwd", "secret",
    "secret_key", "token", "prompt", "response",
    "completion", "tool_args", "tool_arguments",
    "env", "environment_variables",
}


def sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if str(key).strip().lower() in SENSITIVE_KEYS
                else sanitize_value(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_value(item) for item in value]
    if isinstance(value, str) and len(value) > 4096:
        return value[:4096] + "...[TRUNCATED]"
    return value


@dataclass
class DarialClient:
    base_url: str
    api_key: str
    timeout: int = 10
    batch_size: int = 50
    max_queue_size: int = 1000
    max_retries: int = 3
    retry_base_seconds: float = 0.25
    raise_on_failure: bool = False
    _buffer: deque[dict[str, Any]] = field(default_factory=deque)

    @classmethod
    def from_env(cls) -> "DarialClient":
        api_key = os.getenv("TAKT_API_KEY") or os.getenv("DARIAL_API_KEY")
        if not api_key:
            raise KeyError("TAKT_API_KEY")

        return cls(
            base_url=(
                os.getenv("TAKT_BASE_URL")
                or os.getenv("DARIAL_BASE_URL")
                or "http://localhost:8000"
            ),
            api_key=api_key,
            timeout=int(
                os.getenv("TAKT_TIMEOUT")
                or os.getenv("DARIAL_TIMEOUT", "10")
            ),
            batch_size=int(
                os.getenv("TAKT_BATCH_SIZE")
                or os.getenv("DARIAL_BATCH_SIZE", "50")
            ),
            max_queue_size=int(
                os.getenv("TAKT_MAX_QUEUE_SIZE")
                or os.getenv("DARIAL_MAX_QUEUE_SIZE", "1000")
            ),
            max_retries=int(
                os.getenv("TAKT_MAX_RETRIES")
                or os.getenv("DARIAL_MAX_RETRIES", "3")
            ),
        )

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            f"{self.base_url.rstrip('/')}{path}",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with request.urlopen(req, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except (
                error.URLError,
                error.HTTPError,
                TimeoutError,
                ConnectionError,
            ) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(self.retry_base_seconds * (2 ** attempt))

        if self.raise_on_failure and last_error is not None:
            raise last_error

        return {
            "accepted": 0,
            "queued": 1,
            "error": str(last_error) if last_error else "unknown",
        }

    def _event(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        event_id: str | None = None,
        product_id: str | None = None,
        agent_name: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "event_id": event_id or str(uuid.uuid4()),
            "event_type": event_type,
            "product_id": product_id,
            "agent_name": agent_name,
            "trace_id": trace_id,
            "payload": sanitize_value(payload),
        }

    def track_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        event_id: str | None = None,
        product_id: str | None = None,
        agent_name: str | None = None,
        trace_id: str | None = None,
        immediate: bool = False,
    ) -> dict[str, Any]:
        event = self._event(
            event_type,
            payload,
            event_id=event_id,
            product_id=product_id,
            agent_name=agent_name,
            trace_id=trace_id,
        )

        if immediate:
            result = self._post("/api/ingestion/events", event)
            if result.get("queued"):
                self._enqueue(event)
            return result

        self._enqueue(event)
        if len(self._buffer) >= self.batch_size:
            return self.flush()

        return {"accepted": 0, "queued": 1, "queue_size": len(self._buffer)}

    def _enqueue(self, event: dict[str, Any]) -> None:
        if len(self._buffer) >= self.max_queue_size:
            self._buffer.popleft()
        self._buffer.append(event)

    def flush(self) -> dict[str, Any]:
        if not self._buffer:
            return {"accepted": 0, "duplicate": 0, "queued": 0}

        events = list(self._buffer)[: self.batch_size]
        result = self._post(
            "/api/ingestion/events/batch",
            {"events": events},
        )

        if result.get("queued"):
            return {**result, "queue_size": len(self._buffer)}

        for _ in range(min(len(events), len(self._buffer))):
            self._buffer.popleft()

        return {**result, "queue_size": len(self._buffer)}

    def track_run(self, *, agent_name, trace_id, payload, event_id=None,
                  product_id=None, immediate=False):
        return self.track_event(
            "agent_run",
            payload,
            event_id=event_id,
            product_id=product_id,
            agent_name=agent_name,
            trace_id=trace_id,
            immediate=immediate,
        )

    def track_llm_call(self, *, trace_id, model_name, provider,
                       input_tokens, output_tokens, estimated_cost=0,
                       latency_ms=None, event_id=None, immediate=False):
        return self.track_event(
            "llm_call",
            {
                "model_name": model_name,
                "provider": provider,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "estimated_cost": estimated_cost,
                "latency_ms": latency_ms,
            },
            event_id=event_id,
            trace_id=trace_id,
            immediate=immediate,
        )

    def track_tool_call(self, *, trace_id, tool_name, status="completed",
                        latency_ms=None, estimated_cost=0, event_id=None,
                        immediate=False):
        return self.track_event(
            "tool_call",
            {
                "tool_name": tool_name,
                "status": status,
                "latency_ms": latency_ms,
                "estimated_cost": estimated_cost,
            },
            event_id=event_id,
            trace_id=trace_id,
            immediate=immediate,
        )

    def track_outcome(self, *, trace_id, outcome_type, success,
                      quality_score=None, human_accepted=None,
                      time_saved_minutes=None,
                      estimated_business_value=None, event_id=None,
                      immediate=False):
        return self.track_event(
            "business_outcome",
            {
                "outcome_type": outcome_type,
                "success": success,
                "quality_score": quality_score,
                "human_accepted": human_accepted,
                "time_saved_minutes": time_saved_minutes,
                "estimated_business_value": estimated_business_value,
            },
            event_id=event_id,
            trace_id=trace_id,
            immediate=immediate,
        )

    def run(self, workflow: str, *, agent_name: str,
            product_id: str | None = None,
            environment: str = "prod",
            trace_id: str | None = None) -> "DarialRun":
        return DarialRun(
            self,
            workflow,
            agent_name,
            product_id,
            environment,
            trace_id or str(uuid.uuid4()),
        )


@dataclass
class DarialRun:
    client: DarialClient
    workflow: str
    agent_name: str
    product_id: str | None
    environment: str
    trace_id: str
    started_at: float = field(default_factory=time.monotonic)

    def __enter__(self) -> "DarialRun":
        self.client.track_run(
            agent_name=self.agent_name,
            trace_id=self.trace_id,
            product_id=self.product_id,
            payload={
                "workflow_name": self.workflow,
                "environment": self.environment,
                "status": "running",
            },
        )
        return self

    def record_llm_call(self, **kwargs):
        return self.client.track_llm_call(trace_id=self.trace_id, **kwargs)

    def record_tool_call(self, **kwargs):
        return self.client.track_tool_call(trace_id=self.trace_id, **kwargs)

    def record_outcome(self, **kwargs):
        return self.client.track_outcome(trace_id=self.trace_id, **kwargs)

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.client.track_run(
            agent_name=self.agent_name,
            trace_id=self.trace_id,
            product_id=self.product_id,
            payload={
                "workflow_name": self.workflow,
                "environment": self.environment,
                "status": "failed" if exc else "completed",
                "latency_ms": int(
                    (time.monotonic() - self.started_at) * 1000
                ),
                "error_type": exc_type.__name__ if exc_type else None,
            },
        )
        self.client.flush()
        return False
