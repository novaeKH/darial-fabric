from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import text

from app.core.database import SessionLocal
from app.services.kafka_service import publish_json


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("darial.kafka_outbox_publisher")

RUNNING = True

POLL_INTERVAL_SECONDS = float(
    os.getenv("KAFKA_OUTBOX_POLL_INTERVAL_SECONDS", "2")
)
BATCH_SIZE = int(
    os.getenv("KAFKA_OUTBOX_BATCH_SIZE", "100")
)
MAX_RETRIES = int(
    os.getenv("KAFKA_OUTBOX_MAX_RETRIES", "5")
)


def stop_handler(signum, frame):
    global RUNNING
    RUNNING = False
    logger.info("Shutdown signal received: %s", signum)


def ensure_table() -> None:
    with SessionLocal() as db:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS kafka_published_events (
                    id VARCHAR(36) PRIMARY KEY,
                    ingestion_event_id VARCHAR(36) NOT NULL UNIQUE,
                    event_id VARCHAR(128) NOT NULL UNIQUE,
                    topic VARCHAR(255) NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    published_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS
                    ix_kafka_published_events_status
                ON kafka_published_events(status, updated_at)
                """
            )
        )
        db.commit()


def load_candidates(db):
    return db.execute(
        text(
            """
            SELECT
                e.id,
                e.source_id,
                e.event_id,
                e.event_type,
                e.product_id,
                e.agent_name,
                e.trace_id,
                e.payload_json,
                e.received_at
            FROM ingestion_events e
            LEFT JOIN kafka_published_events k
              ON k.ingestion_event_id = e.id
            WHERE 1=1
                /* Stage 14.2.2C3 loop prevention */
                AND NOT EXISTS (
                    SELECT 1
                    FROM kafka_consumed_events kc_loop
                    WHERE kc_loop.event_id = e.event_id
                      AND kc_loop.bridge_status IN (
                          'created',
                          'already_exists'
                      )
                )
                AND
                k.id IS NULL
                OR (
                    k.status = 'failed'
                    AND k.attempts < :max_retries
                )
            ORDER BY e.received_at ASC
            LIMIT :batch_size
            """
        ),
        {
            "max_retries": MAX_RETRIES,
            "batch_size": BATCH_SIZE,
        },
    ).mappings().all()


def reserve_record(db, row) -> None:
    db.execute(
        text(
            """
            INSERT INTO kafka_published_events (
                id,
                ingestion_event_id,
                event_id,
                topic,
                status,
                attempts,
                updated_at
            )
            VALUES (
                :id,
                :ingestion_event_id,
                :event_id,
                :topic,
                'publishing',
                1,
                NOW()
            )
            ON CONFLICT (ingestion_event_id)
            DO UPDATE SET
                status='publishing',
                attempts=kafka_published_events.attempts + 1,
                last_error=NULL,
                updated_at=NOW()
            """
        ),
        {
            "id": str(uuid4()),
            "ingestion_event_id": str(row["id"]),
            "event_id": str(row["event_id"]),
            "topic": os.getenv(
                "KAFKA_TELEMETRY_TOPIC",
                "darial.telemetry.events",
            ),
        },
    )
    db.commit()


def mark_published(db, ingestion_event_id: str) -> None:
    db.execute(
        text(
            """
            UPDATE kafka_published_events
            SET
                status='published',
                published_at=NOW(),
                last_error=NULL,
                updated_at=NOW()
            WHERE ingestion_event_id=:ingestion_event_id
            """
        ),
        {"ingestion_event_id": ingestion_event_id},
    )
    db.commit()


def mark_failed(
    db,
    ingestion_event_id: str,
    error: Exception,
) -> None:
    db.execute(
        text(
            """
            UPDATE kafka_published_events
            SET
                status='failed',
                last_error=:last_error,
                updated_at=NOW()
            WHERE ingestion_event_id=:ingestion_event_id
            """
        ),
        {
            "ingestion_event_id": ingestion_event_id,
            "last_error": str(error)[:4000],
        },
    )
    db.commit()


def normalize_payload(row) -> dict:
    raw_payload = row["payload_json"]

    if isinstance(raw_payload, dict):
        payload = raw_payload
    else:
        try:
            payload = json.loads(raw_payload or "{}")
        except Exception:
            payload = {
                "_raw_payload": raw_payload,
            }

    return {
        "event_id": str(row["event_id"]),
        "event_type": row["event_type"],
        "product_id": (
            str(row["product_id"])
            if row["product_id"] is not None
            else None
        ),
        "source_id": str(row["source_id"]),
        "agent_name": row["agent_name"],
        "trace_id": row["trace_id"],
        "payload": payload,
        "received_at": (
            row["received_at"].isoformat()
            if row["received_at"]
            else datetime.now(timezone.utc).isoformat()
        ),
        "source": "darial-postgres-outbox",
    }


def process_once() -> dict:
    with SessionLocal() as db:
        rows = load_candidates(db)

        published = 0
        failed = 0

        for row in rows:
            ingestion_event_id = str(row["id"])

            try:
                reserve_record(db, row)

                result = publish_json(
                    normalize_payload(row),
                    key=str(row["event_id"]),
                )

                mark_published(
                    db,
                    ingestion_event_id,
                )
                published += 1

                logger.info(
                    "Outbox event published "
                    "event_id=%s ingestion_event_id=%s topic=%s",
                    row["event_id"],
                    ingestion_event_id,
                    result["topic"],
                )

            except Exception as exc:
                db.rollback()

                try:
                    mark_failed(
                        db,
                        ingestion_event_id,
                        exc,
                    )
                except Exception:
                    logger.exception(
                        "Failed to mark Kafka outbox row as failed"
                    )

                failed += 1
                logger.exception(
                    "Outbox publish failed "
                    "event_id=%s ingestion_event_id=%s",
                    row["event_id"],
                    ingestion_event_id,
                )

        return {
            "selected": len(rows),
            "published": published,
            "failed": failed,
        }


def main() -> None:
    ensure_table()

    logger.info(
        "Kafka outbox publisher started "
        "poll=%ss batch=%s retries=%s",
        POLL_INTERVAL_SECONDS,
        BATCH_SIZE,
        MAX_RETRIES,
    )

    while RUNNING:
        try:
            result = process_once()

            if result["selected"]:
                logger.info(
                    "Outbox batch selected=%s published=%s failed=%s",
                    result["selected"],
                    result["published"],
                    result["failed"],
                )

        except Exception:
            logger.exception("Kafka outbox loop failed")

        time.sleep(POLL_INTERVAL_SECONDS)

    logger.info("Kafka outbox publisher stopped")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)

    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
