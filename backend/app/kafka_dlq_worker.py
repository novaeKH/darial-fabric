from __future__ import annotations

import json
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from uuid import uuid4

from confluent_kafka import Consumer, KafkaError, KafkaException
from sqlalchemy import text

from app.core.database import SessionLocal


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("darial.kafka_dlq_worker")

RUNNING = True


def stop_handler(signum, frame):
    global RUNNING
    RUNNING = False
    logger.info("Shutdown signal received: %s", signum)


def bootstrap_servers() -> str:
    return os.getenv("KAFKA_BOOTSTRAP_SERVERS", "redpanda:9092")


def dlq_topic() -> str:
    return os.getenv("KAFKA_DLQ_TOPIC", "darial.telemetry.dlq")


def ensure_table() -> None:
    with SessionLocal() as db:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS kafka_dlq_events (
                    id VARCHAR(36) PRIMARY KEY,
                    dlq_id VARCHAR(128) NOT NULL UNIQUE,
                    source_topic VARCHAR(255),
                    source_partition INTEGER,
                    source_offset BIGINT,
                    error_message TEXT NOT NULL,
                    raw_value TEXT,
                    payload_json JSONB,
                    status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    replay_count INTEGER NOT NULL DEFAULT 0,
                    last_replayed_at TIMESTAMPTZ,
                    resolved_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_kafka_dlq_events_status
                ON kafka_dlq_events(status)
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_kafka_dlq_events_created_at
                ON kafka_dlq_events(created_at DESC)
                """
            )
        )
        db.commit()


def config() -> dict:
    return {
        "bootstrap.servers": bootstrap_servers(),
        "group.id": os.getenv(
            "KAFKA_DLQ_CONSUMER_GROUP",
            "darial-telemetry-dlq-registry-v1",
        ),
        "auto.offset.reset": os.getenv(
            "KAFKA_DLQ_AUTO_OFFSET_RESET",
            "earliest",
        ),
        "enable.auto.commit": False,
        "session.timeout.ms": 10000,
        "max.poll.interval.ms": 300000,
    }


def parse_message(message) -> dict:
    if not message.value():
        raise ValueError("DLQ message has empty value")

    body = json.loads(message.value().decode("utf-8"))
    if not isinstance(body, dict):
        raise ValueError("DLQ message must be a JSON object")

    dlq_id = body.get("dlq_id")
    if not dlq_id:
        raise ValueError("dlq_id is required")

    return body


def store_message(body: dict) -> str:
    with SessionLocal() as db:
        exists = db.execute(
            text(
                """
                SELECT id
                FROM kafka_dlq_events
                WHERE dlq_id=:dlq_id
                """
            ),
            {"dlq_id": str(body["dlq_id"])},
        ).scalar()

        if exists:
            return "duplicate"

        raw_value = body.get("raw_value")
        parsed_payload = None
        if isinstance(raw_value, str):
            try:
                candidate = json.loads(raw_value)
                if isinstance(candidate, dict):
                    parsed_payload = candidate
            except Exception:
                parsed_payload = None

        db.execute(
            text(
                """
                INSERT INTO kafka_dlq_events (
                    id,
                    dlq_id,
                    source_topic,
                    source_partition,
                    source_offset,
                    error_message,
                    raw_value,
                    payload_json,
                    status,
                    created_at
                )
                VALUES (
                    :id,
                    :dlq_id,
                    :source_topic,
                    :source_partition,
                    :source_offset,
                    :error_message,
                    :raw_value,
                    CAST(:payload_json AS JSONB),
                    'pending',
                    :created_at
                )
                """
            ),
            {
                "id": str(uuid4()),
                "dlq_id": str(body["dlq_id"]),
                "source_topic": body.get("source_topic"),
                "source_partition": body.get("source_partition"),
                "source_offset": body.get("source_offset"),
                "error_message": str(
                    body.get("error") or "Unknown DLQ error"
                ),
                "raw_value": raw_value,
                "payload_json": json.dumps(
                    parsed_payload,
                    ensure_ascii=False,
                ) if parsed_payload is not None else "null",
                "created_at": (
                    body.get("failed_at")
                    or datetime.now(timezone.utc).isoformat()
                ),
            },
        )
        db.commit()
        return "stored"


def main() -> None:
    ensure_table()

    consumer = Consumer(config())
    consumer.subscribe([dlq_topic()])

    logger.info(
        "Kafka DLQ registry started topic=%s group=%s",
        dlq_topic(),
        config()["group.id"],
    )

    try:
        while RUNNING:
            message = consumer.poll(1.0)

            if message is None:
                continue

            if message.error():
                if message.error().code() == KafkaError._PARTITION_EOF:
                    continue
                raise KafkaException(message.error())

            try:
                body = parse_message(message)
                result = store_message(body)

                logger.info(
                    "DLQ event %s dlq_id=%s partition=%s offset=%s",
                    result,
                    body["dlq_id"],
                    message.partition(),
                    message.offset(),
                )

                consumer.commit(
                    message=message,
                    asynchronous=False,
                )
            except Exception:
                logger.exception(
                    "Failed to register DLQ message "
                    "partition=%s offset=%s; offset not committed",
                    message.partition(),
                    message.offset(),
                )

    finally:
        consumer.close()
        logger.info("Kafka DLQ registry stopped")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)

    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
