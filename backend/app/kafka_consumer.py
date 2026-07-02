from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from uuid import uuid4

from confluent_kafka import Consumer, KafkaError, KafkaException, Producer
from sqlalchemy import text

from app.core.database import SessionLocal


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("darial.kafka_consumer")

RUNNING = True

ALLOWED_EVENT_TYPES = {
    "agent_run",
    "llm_call",
    "tool_call",
    "business_outcome",
}


def stop_handler(signum, frame):
    global RUNNING
    RUNNING = False
    logger.info("Shutdown signal received: %s", signum)


def bootstrap_servers() -> str:
    return os.getenv("KAFKA_BOOTSTRAP_SERVERS", "redpanda:9092")


def telemetry_topic() -> str:
    return os.getenv(
        "KAFKA_TELEMETRY_TOPIC",
        "darial.telemetry.events",
    )


def dlq_topic() -> str:
    return os.getenv(
        "KAFKA_DLQ_TOPIC",
        "darial.telemetry.dlq",
    )


def ensure_table() -> None:
    with SessionLocal() as db:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS kafka_consumed_events (
                    id VARCHAR(36) PRIMARY KEY,
                    event_id VARCHAR(128) NOT NULL UNIQUE,
                    topic VARCHAR(255) NOT NULL,
                    partition_id INTEGER NOT NULL,
                    offset_value BIGINT NOT NULL,
                    event_type VARCHAR(64),
                    product_id VARCHAR(128),
                    payload_json TEXT NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'accepted',
                    error_message TEXT,
                    consumed_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS
                    ix_kafka_consumed_events_consumed_at
                ON kafka_consumed_events(consumed_at)
                """
            )
        )
        db.commit()


def consumer_config() -> dict:
    return {
        "bootstrap.servers": bootstrap_servers(),
        "group.id": os.getenv(
            "KAFKA_CONSUMER_GROUP",
            "darial-telemetry-shadow-v1",
        ),
        "auto.offset.reset": os.getenv(
            "KAFKA_AUTO_OFFSET_RESET",
            "earliest",
        ),
        "enable.auto.commit": False,
        "enable.partition.eof": False,
        "session.timeout.ms": 10000,
        "max.poll.interval.ms": 300000,
    }


def producer_config() -> dict:
    return {
        "bootstrap.servers": bootstrap_servers(),
        "client.id": "darial-kafka-shadow-consumer",
        "acks": "all",
        "enable.idempotence": True,
    }


def publish_dlq(
    producer: Producer,
    *,
    message,
    error: str,
) -> None:
    body = {
        "dlq_id": str(uuid4()),
        "source_topic": message.topic(),
        "source_partition": message.partition(),
        "source_offset": message.offset(),
        "error": error,
        "raw_value": (
            message.value().decode("utf-8", errors="replace")
            if message.value()
            else None
        ),
        "failed_at": datetime.now(timezone.utc).isoformat(),
    }

    producer.produce(
        dlq_topic(),
        key=(
            message.key()
            or str(body["dlq_id"]).encode("utf-8")
        ),
        value=json.dumps(
            body,
            ensure_ascii=False,
        ).encode("utf-8"),
    )
    producer.flush(10)


def normalize_event(message) -> dict:
    if not message.value():
        raise ValueError("Kafka message has empty value")

    try:
        body = json.loads(message.value().decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc

    if not isinstance(body, dict):
        raise ValueError("Kafka event must be a JSON object")

    event_id = body.get("event_id")
    if not event_id:
        raise ValueError("event_id is required")

    event_type = body.get("event_type")
    if event_type not in ALLOWED_EVENT_TYPES:
        raise ValueError(
            f"Unsupported event_type: {event_type!r}"
        )

    payload = body.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")

    return body


def store_event(message, body: dict) -> str:
    with SessionLocal() as db:
        existing = db.execute(
            text(
                """
                SELECT id
                FROM kafka_consumed_events
                WHERE event_id=:event_id
                """
            ),
            {"event_id": str(body["event_id"])},
        ).scalar()

        if existing:
            return "duplicate"

        db.execute(
            text(
                """
                INSERT INTO kafka_consumed_events (
                    id,
                    event_id,
                    topic,
                    partition_id,
                    offset_value,
                    event_type,
                    product_id,
                    payload_json,
                    status,
                    consumed_at
                )
                VALUES (
                    :id,
                    :event_id,
                    :topic,
                    :partition_id,
                    :offset_value,
                    :event_type,
                    :product_id,
                    :payload_json,
                    'accepted',
                    :consumed_at
                )
                """
            ),
            {
                "id": str(uuid4()),
                "event_id": str(body["event_id"]),
                "topic": message.topic(),
                "partition_id": message.partition(),
                "offset_value": message.offset(),
                "event_type": body.get("event_type"),
                "product_id": body.get("product_id"),
                "payload_json": json.dumps(
                    body,
                    ensure_ascii=False,
                    default=str,
                ),
                "consumed_at": datetime.now(timezone.utc),
            },
        )
        db.commit()
        return "accepted"


def main() -> None:
    ensure_table()

    consumer = Consumer(consumer_config())
    producer = Producer(producer_config())

    consumer.subscribe([telemetry_topic()])
    logger.info(
        "Kafka shadow consumer started topic=%s group=%s",
        telemetry_topic(),
        consumer_config()["group.id"],
    )

    try:
        while RUNNING:
            message = consumer.poll(1.0)

            if message is None:
                continue

            if message.error():
                if (
                    message.error().code()
                    == KafkaError._PARTITION_EOF
                ):
                    continue
                raise KafkaException(message.error())

            try:
                body = normalize_event(message)
                result = store_event(message, body)

                logger.info(
                    "Kafka event %s event_id=%s "
                    "partition=%s offset=%s",
                    result,
                    body["event_id"],
                    message.partition(),
                    message.offset(),
                )

                consumer.commit(
                    message=message,
                    asynchronous=False,
                )

            except Exception as exc:
                logger.exception(
                    "Kafka event rejected topic=%s "
                    "partition=%s offset=%s",
                    message.topic(),
                    message.partition(),
                    message.offset(),
                )

                try:
                    publish_dlq(
                        producer,
                        message=message,
                        error=str(exc),
                    )
                    consumer.commit(
                        message=message,
                        asynchronous=False,
                    )
                except Exception:
                    logger.exception(
                        "Failed to publish event to DLQ; "
                        "offset will not be committed"
                    )
                    time.sleep(2)

    finally:
        consumer.close()
        producer.flush(5)
        logger.info("Kafka shadow consumer stopped")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)

    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
