from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from sqlalchemy import inspect, text

from app.core.database import SessionLocal, engine


router = APIRouter(
    prefix="/api/kafka/health",
    tags=["Kafka Health"],
)


def _table_exists(name: str) -> bool:
    return inspect(engine).has_table(name)


def _columns(name: str) -> set[str]:
    if not _table_exists(name):
        return set()

    return {
        column["name"]
        for column in inspect(engine).get_columns(name)
    }


def _scalar(db, sql: str, params: dict[str, Any] | None = None):
    return db.execute(
        text(sql),
        params or {},
    ).scalar()


def _iso(value: Any) -> str | None:
    if value is None:
        return None

    if hasattr(value, "isoformat"):
        return value.isoformat()

    return str(value)


@router.get("/summary")
def get_kafka_pipeline_health():
    now = datetime.now(timezone.utc)

    result: dict[str, Any] = {
        "status": "idle",
        "checked_at": now.isoformat(),
        "producer": {
            "published_total": 0,
            "failed_total": 0,
            "last_published_at": None,
        },
        "consumer": {
            "consumed_total": 0,
            "last_consumed_at": None,
            "bridge_created_total": 0,
        },
        "ingestion": {
            "accepted": 0,
            "processing": 0,
            "retry": 0,
            "dead_letter": 0,
        },
        "dlq": {
            "pending": 0,
            "replayed": 0,
            "resolved": 0,
            "last_event_at": None,
        },
        "signals": [],
    }

    with SessionLocal() as db:
        published_columns = _columns("kafka_published_events")

        if published_columns:
            result["producer"]["published_total"] = int(
                _scalar(
                    db,
                    "SELECT COUNT(*) FROM kafka_published_events",
                )
                or 0
            )

            if "status" in published_columns:
                result["producer"]["failed_total"] = int(
                    _scalar(
                        db,
                        """
                        SELECT COUNT(*)
                        FROM kafka_published_events
                        WHERE status IN ('failed', 'error')
                        """,
                    )
                    or 0
                )

            for candidate in (
                "published_at",
                "updated_at",
                "created_at",
            ):
                if candidate in published_columns:
                    value = _scalar(
                        db,
                        f"""
                        SELECT MAX({candidate})
                        FROM kafka_published_events
                        """,
                    )
                    result["producer"]["last_published_at"] = _iso(
                        value
                    )
                    break

        consumed_columns = _columns("kafka_consumed_events")

        if consumed_columns:
            result["consumer"]["consumed_total"] = int(
                _scalar(
                    db,
                    "SELECT COUNT(*) FROM kafka_consumed_events",
                )
                or 0
            )

            if "consumed_at" in consumed_columns:
                value = _scalar(
                    db,
                    """
                    SELECT MAX(consumed_at)
                    FROM kafka_consumed_events
                    """,
                )
                result["consumer"]["last_consumed_at"] = _iso(value)

            if "bridge_status" in consumed_columns:
                result["consumer"]["bridge_created_total"] = int(
                    _scalar(
                        db,
                        """
                        SELECT COUNT(*)
                        FROM kafka_consumed_events
                        WHERE bridge_status IN (
                            'created',
                            'already_exists'
                        )
                        """,
                    )
                    or 0
                )

        ingestion_columns = _columns("ingestion_events")

        if ingestion_columns and "status" in ingestion_columns:
            rows = db.execute(
                text(
                    """
                    SELECT status, COUNT(*) AS count
                    FROM ingestion_events
                    WHERE status IN (
                        'accepted',
                        'processing',
                        'retry',
                        'dead_letter'
                    )
                    GROUP BY status
                    """
                )
            ).mappings().all()

            for row in rows:
                result["ingestion"][row["status"]] = int(
                    row["count"]
                )

        dlq_columns = _columns("kafka_dlq_events")

        if dlq_columns:
            rows = db.execute(
                text(
                    """
                    SELECT status, COUNT(*) AS count
                    FROM kafka_dlq_events
                    GROUP BY status
                    """
                )
            ).mappings().all()

            for row in rows:
                status = row["status"]
                if status in result["dlq"]:
                    result["dlq"][status] = int(row["count"])

            if "created_at" in dlq_columns:
                value = _scalar(
                    db,
                    """
                    SELECT MAX(created_at)
                    FROM kafka_dlq_events
                    """,
                )
                result["dlq"]["last_event_at"] = _iso(value)

    signals: list[dict[str, Any]] = []

    if result["producer"]["failed_total"] > 0:
        signals.append(
            {
                "level": "critical",
                "code": "kafka_publish_failures",
                "message": (
                    "Есть неуспешные публикации в Kafka"
                ),
                "value": result["producer"]["failed_total"],
            }
        )

    if result["ingestion"]["dead_letter"] > 0:
        signals.append(
            {
                "level": "critical",
                "code": "ingestion_dead_letter",
                "message": (
                    "Есть события ingestion в dead_letter"
                ),
                "value": result["ingestion"]["dead_letter"],
            }
        )

    if result["ingestion"]["retry"] > 0:
        signals.append(
            {
                "level": "warning",
                "code": "ingestion_retry",
                "message": (
                    "Есть события ingestion в повторной обработке"
                ),
                "value": result["ingestion"]["retry"],
            }
        )

    if result["ingestion"]["processing"] > 20:
        signals.append(
            {
                "level": "warning",
                "code": "processing_backlog",
                "message": (
                    "Необычно много событий находится в processing"
                ),
                "value": result["ingestion"]["processing"],
            }
        )

    if result["dlq"]["pending"] > 0:
        signals.append(
            {
                "level": "warning",
                "code": "pending_dlq",
                "message": (
                    "Есть DLQ-события, требующие внимания"
                ),
                "value": result["dlq"]["pending"],
            }
        )

    result["signals"] = signals

    levels = {signal["level"] for signal in signals}

    if "critical" in levels:
        result["status"] = "critical"
    elif "warning" in levels:
        result["status"] = "warning"
    elif (
        result["producer"]["published_total"] > 0
        or result["consumer"]["consumed_total"] > 0
    ):
        result["status"] = "healthy"
    else:
        result["status"] = "idle"

    return result
