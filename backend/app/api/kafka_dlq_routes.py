from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from confluent_kafka import Producer
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from app.core.database import SessionLocal


router = APIRouter(prefix="/api/kafka/dlq", tags=["Kafka DLQ"])


def _bootstrap_servers() -> str:
    return os.getenv("KAFKA_BOOTSTRAP_SERVERS", "redpanda:9092")


def _telemetry_topic() -> str:
    return os.getenv(
        "KAFKA_TELEMETRY_TOPIC",
        "darial.telemetry.events",
    )


def _producer() -> Producer:
    return Producer(
        {
            "bootstrap.servers": _bootstrap_servers(),
            "client.id": "darial-dlq-replay-api",
            "acks": "all",
            "enable.idempotence": True,
        }
    )


class DLQResolveRequest(BaseModel):
    note: str | None = None


def _row_to_dict(row: Any) -> dict[str, Any]:
    result = dict(row)
    for key, value in list(result.items()):
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
    return result


@router.get("")
def list_dlq_events(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    filters = []
    params: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
    }

    if status:
        filters.append("status=:status")
        params["status"] = status

    where_sql = (
        "WHERE " + " AND ".join(filters)
        if filters
        else ""
    )

    with SessionLocal() as db:
        total = db.execute(
            text(
                f"""
                SELECT COUNT(*)
                FROM kafka_dlq_events
                {where_sql}
                """
            ),
            params,
        ).scalar_one()

        rows = db.execute(
            text(
                f"""
                SELECT
                    id,
                    dlq_id,
                    source_topic,
                    source_partition,
                    source_offset,
                    error_message,
                    payload_json,
                    status,
                    replay_count,
                    last_replayed_at,
                    resolved_at,
                    created_at
                FROM kafka_dlq_events
                {where_sql}
                ORDER BY created_at DESC
                LIMIT :limit
                OFFSET :offset
                """
            ),
            params,
        ).mappings().all()

    return {
        "items": [_row_to_dict(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{dlq_id}")
def get_dlq_event(dlq_id: str):
    with SessionLocal() as db:
        row = db.execute(
            text(
                """
                SELECT *
                FROM kafka_dlq_events
                WHERE dlq_id=:dlq_id
                """
            ),
            {"dlq_id": dlq_id},
        ).mappings().first()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="DLQ event not found",
        )

    return _row_to_dict(row)


@router.post("/{dlq_id}/replay")
def replay_dlq_event(dlq_id: str):
    with SessionLocal() as db:
        row = db.execute(
            text(
                """
                SELECT *
                FROM kafka_dlq_events
                WHERE dlq_id=:dlq_id
                FOR UPDATE
                """
            ),
            {"dlq_id": dlq_id},
        ).mappings().first()

        if not row:
            raise HTTPException(
                status_code=404,
                detail="DLQ event not found",
            )

        raw_value = row["raw_value"]
        if not raw_value:
            raise HTTPException(
                status_code=422,
                detail="DLQ event has no raw_value to replay",
            )

        try:
            parsed = json.loads(raw_value)
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail=f"raw_value is not valid JSON: {exc}",
            ) from exc

        if not isinstance(parsed, dict):
            raise HTTPException(
                status_code=422,
                detail="raw_value must contain a JSON object",
            )

        producer = _producer()
        delivery_error: list[str] = []

        def delivery_callback(err, msg):
            if err is not None:
                delivery_error.append(str(err))

        producer.produce(
            _telemetry_topic(),
            key=str(
                parsed.get("event_id") or dlq_id
            ).encode("utf-8"),
            value=json.dumps(
                parsed,
                ensure_ascii=False,
            ).encode("utf-8"),
            on_delivery=delivery_callback,
        )

        remaining = producer.flush(10)
        if remaining or delivery_error:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Kafka replay failed: "
                    + (
                        "; ".join(delivery_error)
                        if delivery_error
                        else f"{remaining} message(s) pending"
                    )
                ),
            )

        now = datetime.now(timezone.utc)

        db.execute(
            text(
                """
                UPDATE kafka_dlq_events
                SET
                    status='replayed',
                    replay_count=replay_count + 1,
                    last_replayed_at=:now
                WHERE dlq_id=:dlq_id
                """
            ),
            {
                "dlq_id": dlq_id,
                "now": now,
            },
        )
        db.commit()

    return {
        "dlq_id": dlq_id,
        "status": "replayed",
        "replayed_to": _telemetry_topic(),
        "replayed_at": now.isoformat(),
    }


@router.post("/{dlq_id}/resolve")
def resolve_dlq_event(
    dlq_id: str,
    body: DLQResolveRequest | None = None,
):
    with SessionLocal() as db:
        exists = db.execute(
            text(
                """
                SELECT id
                FROM kafka_dlq_events
                WHERE dlq_id=:dlq_id
                """
            ),
            {"dlq_id": dlq_id},
        ).scalar()

        if not exists:
            raise HTTPException(
                status_code=404,
                detail="DLQ event not found",
            )

        now = datetime.now(timezone.utc)

        db.execute(
            text(
                """
                UPDATE kafka_dlq_events
                SET
                    status='resolved',
                    resolved_at=:now
                WHERE dlq_id=:dlq_id
                """
            ),
            {
                "dlq_id": dlq_id,
                "now": now,
            },
        )
        db.commit()

    return {
        "dlq_id": dlq_id,
        "status": "resolved",
        "resolved_at": now.isoformat(),
        "note": body.note if body else None,
    }
