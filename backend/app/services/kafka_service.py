from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from confluent_kafka import Producer

logger = logging.getLogger(__name__)


def _delivery_report(error, message) -> None:
    if error is not None:
        logger.error("Kafka delivery failed: %s", error)
    else:
        logger.info(
            "Kafka event delivered topic=%s partition=%s offset=%s",
            message.topic(),
            message.partition(),
            message.offset(),
        )


def kafka_config() -> dict[str, Any]:
    return {
        "bootstrap.servers": os.getenv(
            "KAFKA_BOOTSTRAP_SERVERS",
            "redpanda:9092",
        ),
        "client.id": os.getenv("KAFKA_CLIENT_ID", "darial-backend"),
        "acks": "all",
        "enable.idempotence": True,
        "message.send.max.retries": 3,
        "retry.backoff.ms": 500,
        "socket.timeout.ms": 5000,
    }


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


def publish_json(
    payload: dict[str, Any],
    *,
    topic: str | None = None,
    key: str | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    destination = topic or telemetry_topic()
    producer = Producer(kafka_config())

    event_id = str(payload.get("event_id") or uuid4())
    body = {
        **payload,
        "event_id": event_id,
        "published_at": datetime.now(timezone.utc).isoformat(),
    }

    producer.produce(
        destination,
        key=(key or event_id).encode("utf-8"),
        value=json.dumps(body, ensure_ascii=False, default=str).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-darial-event-id": event_id,
        },
        on_delivery=_delivery_report,
    )

    remaining = producer.flush(timeout)
    if remaining:
        raise RuntimeError(
            f"Kafka producer flush timed out; {remaining} message(s) remain"
        )

    return {
        "status": "published",
        "topic": destination,
        "event_id": event_id,
    }


def kafka_status() -> dict[str, Any]:
    try:
        producer = Producer(kafka_config())
        metadata = producer.list_topics(timeout=5)
        topics = sorted(metadata.topics.keys())

        return {
            "status": "ok",
            "bootstrap_servers": kafka_config()["bootstrap.servers"],
            "telemetry_topic": telemetry_topic(),
            "dlq_topic": dlq_topic(),
            "topics": topics,
        }
    except Exception as exc:
        logger.exception("Kafka status check failed")
        return {
            "status": "unavailable",
            "bootstrap_servers": kafka_config()["bootstrap.servers"],
            "error": str(exc),
        }
