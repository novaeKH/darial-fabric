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

BRIDGE_ENABLED = (
    os.getenv("KAFKA_BRIDGE_TO_INGESTION", "true").lower()
    in {"1", "true", "yes", "on"}
)


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


def ensure_tables() -> None:
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
                ALTER TABLE kafka_consumed_events
                ADD COLUMN IF NOT EXISTS ingestion_event_id VARCHAR(64)
                """
            )
        )
        db.execute(
            text(
                """
                ALTER TABLE kafka_consumed_events
                ADD COLUMN IF NOT EXISTS bridge_status VARCHAR(32)
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
            "darial-telemetry-bridge-v1",
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
        "client.id": "darial-kafka-bridge-consumer",
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


def ensure_kafka_source(db, product_id: str | None) -> str:
    source_id = db.execute(
        text(
            """
            SELECT id
            FROM ingestion_sources
            WHERE name='Kafka Telemetry Bridge'
            ORDER BY created_at
            LIMIT 1
            """
        )
    ).scalar()

    if source_id:
        return str(source_id)

    source_id = str(uuid4())

    db.execute(
        text(
            """
            INSERT INTO ingestion_sources (
                id,
                name,
                source_type,
                product_id,
                environment,
                status,
                metadata_json,
                created_at
            )
            VALUES (
                :id,
                'Kafka Telemetry Bridge',
                'kafka',
                :product_id,
                'production',
                'active',
                CAST(:metadata_json AS JSONB),
                NOW()
            )
            """
        ),
        {
            "id": source_id,
            "product_id": product_id,
            "metadata_json": json.dumps(
                {
                    "bootstrap_servers": bootstrap_servers(),
                    "topic": telemetry_topic(),
                    "managed_by": "darial",
                }
            ),
        },
    )

    return source_id


def bridge_to_ingestion(db, body: dict) -> tuple[str, str]:
    event_id = str(body["event_id"])

    existing = db.execute(
        text(
            """
            SELECT id, status
            FROM ingestion_events
            WHERE event_id=:event_id
            """
        ),
        {"event_id": event_id},
    ).mappings().first()

    if existing:
        return str(existing["id"]), "already_exists"

    product_id = body.get("product_id")
    source_id = body.get("source_id")

    if source_id:
        source_exists = db.execute(
            text(
                """
                SELECT id
                FROM ingestion_sources
                WHERE id=:source_id
                """
            ),
            {"source_id": str(source_id)},
        ).scalar()

        if not source_exists:
            source_id = None

    if not source_id:
        source_id = ensure_kafka_source(
            db,
            str(product_id) if product_id else None,
        )

    ingestion_event_id = str(uuid4())

    db.execute(
        text(
            """
            INSERT INTO ingestion_events (
                id,
                source_id,
                event_id,
                event_type,
                product_id,
                agent_name,
                trace_id,
                payload_json,
                received_at,
                status,
                retry_count
            )
            VALUES (
                :id,
                :source_id,
                :event_id,
                :event_type,
                :product_id,
                :agent_name,
                :trace_id,
                CAST(:payload_json AS JSONB),
                NOW(),
                'accepted',
                0
            )
            """
        ),
        {
            "id": ingestion_event_id,
            "source_id": str(source_id),
            "event_id": event_id,
            "event_type": body["event_type"],
            "product_id": (
                str(product_id)
                if product_id is not None
                else None
            ),
            "agent_name": (
                body.get("agent_name")
                or body.get("payload", {}).get("agent_name")
            ),
            "trace_id": body.get("trace_id"),
            "payload_json": json.dumps(
                body["payload"],
                ensure_ascii=False,
                default=str,
            ),
        },
    )

    return ingestion_event_id, "created"


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

        ingestion_event_id = None
        bridge_status = "disabled"

        if BRIDGE_ENABLED:
            ingestion_event_id, bridge_status = bridge_to_ingestion(
                db,
                body,
            )

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
                    ingestion_event_id,
                    bridge_status,
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
                    :ingestion_event_id,
                    :bridge_status,
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
                "ingestion_event_id": ingestion_event_id,
                "bridge_status": bridge_status,
                "consumed_at": datetime.now(timezone.utc),
            },
        )

        db.commit()

        if bridge_status == "created":
            return "accepted_and_bridged"

        if bridge_status == "already_exists":
            return "accepted_existing_ingestion_event"

        return "accepted"


def main() -> None:
    ensure_tables()

    consumer = Consumer(consumer_config())
    producer = Producer(producer_config())

    consumer.subscribe([telemetry_topic()])
    logger.info(
        "Kafka bridge consumer started "
        "topic=%s group=%s bridge=%s",
        telemetry_topic(),
        consumer_config()["group.id"],
        BRIDGE_ENABLED,
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
        logger.info("Kafka bridge consumer stopped")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)

    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
