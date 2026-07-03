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

from app.api.kafka_health_routes import get_kafka_pipeline_health
from app.core.database import SessionLocal


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("darial.kafka_health_snapshot_worker")

RUNNING = True


def stop_handler(signum, frame):
    global RUNNING
    RUNNING = False
    logger.info("Shutdown signal received: %s", signum)


def interval_seconds() -> int:
    value = int(
        os.getenv(
            "KAFKA_HEALTH_SNAPSHOT_INTERVAL_SECONDS",
            "60",
        )
    )
    return max(30, value)


def ensure_table() -> None:
    with SessionLocal() as db:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS
                    kafka_pipeline_health_snapshots (
                        id VARCHAR(36) PRIMARY KEY,
                        status VARCHAR(32) NOT NULL,
                        published_total BIGINT NOT NULL DEFAULT 0,
                        consumed_total BIGINT NOT NULL DEFAULT 0,
                        ingestion_backlog BIGINT NOT NULL DEFAULT 0,
                        ingestion_retry BIGINT NOT NULL DEFAULT 0,
                        ingestion_dead_letter BIGINT NOT NULL DEFAULT 0,
                        dlq_pending BIGINT NOT NULL DEFAULT 0,
                        dlq_replayed BIGINT NOT NULL DEFAULT 0,
                        signal_count INTEGER NOT NULL DEFAULT 0,
                        payload_json JSONB NOT NULL,
                        captured_at TIMESTAMPTZ NOT NULL
                    )
                """
            )
        )

        db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS
                    ix_kafka_pipeline_health_snapshots_captured_at
                ON kafka_pipeline_health_snapshots(
                    captured_at DESC
                )
                """
            )
        )

        db.commit()


def capture_snapshot() -> None:
    health = get_kafka_pipeline_health()

    ingestion = health["ingestion"]
    dlq = health["dlq"]

    backlog = (
        int(ingestion["accepted"])
        + int(ingestion["processing"])
        + int(ingestion["retry"])
    )

    captured_at = datetime.now(timezone.utc)

    with SessionLocal() as db:
        db.execute(
            text(
                """
                INSERT INTO kafka_pipeline_health_snapshots (
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
                )
                VALUES (
                    :id,
                    :status,
                    :published_total,
                    :consumed_total,
                    :ingestion_backlog,
                    :ingestion_retry,
                    :ingestion_dead_letter,
                    :dlq_pending,
                    :dlq_replayed,
                    :signal_count,
                    CAST(:payload_json AS JSONB),
                    :captured_at
                )
                """
            ),
            {
                "id": str(uuid4()),
                "status": health["status"],
                "published_total": int(
                    health["producer"]["published_total"]
                ),
                "consumed_total": int(
                    health["consumer"]["consumed_total"]
                ),
                "ingestion_backlog": backlog,
                "ingestion_retry": int(ingestion["retry"]),
                "ingestion_dead_letter": int(
                    ingestion["dead_letter"]
                ),
                "dlq_pending": int(dlq["pending"]),
                "dlq_replayed": int(dlq["replayed"]),
                "signal_count": len(health["signals"]),
                "payload_json": json.dumps(
                    health,
                    ensure_ascii=False,
                    default=str,
                ),
                "captured_at": captured_at,
            },
        )

        db.execute(
            text(
                """
                DELETE FROM kafka_pipeline_health_snapshots
                WHERE captured_at < NOW() - INTERVAL '30 days'
                """
            )
        )

        db.commit()

    logger.info(
        "Kafka health snapshot captured status=%s "
        "backlog=%s dead_letter=%s pending_dlq=%s",
        health["status"],
        backlog,
        ingestion["dead_letter"],
        dlq["pending"],
    )


def main() -> None:
    ensure_table()
    delay = interval_seconds()

    logger.info(
        "Kafka health snapshot worker started interval=%ss",
        delay,
    )

    while RUNNING:
        started = time.monotonic()

        try:
            capture_snapshot()
        except Exception:
            logger.exception(
                "Failed to capture Kafka health snapshot"
            )

        elapsed = time.monotonic() - started
        remaining = max(1.0, delay - elapsed)

        slept = 0.0
        while RUNNING and slept < remaining:
            step = min(1.0, remaining - slept)
            time.sleep(step)
            slept += step

    logger.info("Kafka health snapshot worker stopped")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)

    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
