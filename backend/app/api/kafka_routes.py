from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.kafka_service import kafka_status, publish_json


router = APIRouter(prefix="/kafka", tags=["Kafka"])


class KafkaTestEvent(BaseModel):
    event_type: str = Field(default="agent_run")
    product_id: str | None = None
    payload: dict = Field(default_factory=dict)


@router.get("/status")
def get_kafka_status():
    return kafka_status()


@router.post("/test-event")
def publish_test_event(body: KafkaTestEvent):
    event_id = str(uuid4())

    return publish_json(
        {
            "event_id": event_id,
            "event_type": body.event_type,
            "product_id": body.product_id,
            "payload": body.payload,
            "source": "darial-stage14.2.2a",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        },
        key=event_id,
    )
