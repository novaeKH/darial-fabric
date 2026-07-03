from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query
from sqlalchemy import text

from app.core.database import SessionLocal


router = APIRouter(
    prefix="/api/kafka/health/history",
    tags=["Kafka Health History"],
)


@router.get("")
def get_kafka_health_history(
    hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=500, ge=1, le=5000),
):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                SELECT
                    id,
                    status,
                    published_total,
                    consumed_total,
                    ingestion_backlog,
                    ingestion_retry,
                    ingestion_dead_letter,
                    dlq_pending,
                    dlq_replayed,
                    signal_count,
                    captured_at
                FROM kafka_pipeline_health_snapshots
                WHERE captured_at >= :since
                ORDER BY captured_at ASC
                LIMIT :limit
                """
            ),
            {
                "since": since,
                "limit": limit,
            },
        ).mappings().all()

    return {
        "hours": hours,
        "count": len(rows),
        "items": [
            {
                **dict(row),
                "captured_at": row["captured_at"].isoformat(),
            }
            for row in rows
        ],
    }


@router.get("/latest")
def get_latest_kafka_health_snapshot():
    with SessionLocal() as db:
        row = db.execute(
            text(
                """
                SELECT
                    id,
                    status,
                    published_total,
                    consumed_total,
                    ingestion_backlog,
                    ingestion_retry,
                    ingestion_dead_letter,
                    dlq_pending,
                    dlq_replayed,
                    signal_count,
                    payload_json,
                    captured_at
                FROM kafka_pipeline_health_snapshots
                ORDER BY captured_at DESC
                LIMIT 1
                """
            )
        ).mappings().first()

    if not row:
        return {
            "snapshot": None,
        }

    result = dict(row)
    result["captured_at"] = row["captured_at"].isoformat()

    return {
        "snapshot": result,
    }
