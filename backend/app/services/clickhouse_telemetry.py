from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

TABLE_BY_EVENT = {
    "agent_run": "agent_runs",
    "llm_call": "llm_calls",
    "tool_call": "tool_calls",
    "business_outcome": "business_outcomes",
}


def _client():
    import clickhouse_connect

    return clickhouse_connect.get_client(
        host=os.getenv("CLICKHOUSE_HOST", "clickhouse"),
        port=int(os.getenv("CLICKHOUSE_PORT", "8123")),
        username=os.getenv("CLICKHOUSE_USER", "default"),
        password=os.getenv("CLICKHOUSE_PASSWORD", ""),
        database=os.getenv("CLICKHOUSE_DATABASE", "darial"),
        connect_timeout=3,
        send_receive_timeout=10,
    )


def _json_default(value: Any):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _serialize_model(item) -> dict:
    return {
        column.name: getattr(item, column.name)
        for column in item.__table__.columns
    }


def ensure_clickhouse_schema() -> None:
    client = _client()
    for table in (
        "telemetry_agent_runs",
        "telemetry_llm_calls",
        "telemetry_tool_calls",
        "telemetry_business_outcomes",
    ):
        client.command(
            f'''
            CREATE TABLE IF NOT EXISTS {table}
            (
                entity_id String,
                product_id Nullable(String),
                run_id Nullable(String),
                event_time DateTime64(3),
                payload_json String,
                synced_at DateTime64(3)
            )
            ENGINE = ReplacingMergeTree(synced_at)
            ORDER BY entity_id
            '''
        )


def _resolve_model(event_type: str):
    from app.models.observability import (
        AgentRun,
        BusinessOutcome,
        LLMCall,
        ToolCall,
    )

    return {
        "agent_run": AgentRun,
        "llm_call": LLMCall,
        "tool_call": ToolCall,
        "business_outcome": BusinessOutcome,
    }[event_type]


def _product_id(db: Session, event_type: str, item) -> str | None:
    direct = getattr(item, "product_id", None)
    if direct:
        return str(direct)

    run_id = getattr(item, "run_id", None)
    if not run_id:
        return None

    from app.models.observability import AgentRun

    run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
    return str(run.product_id) if run else None


def mirror_entity(db: Session, event_type: str, entity_id: str) -> bool:
    if event_type not in TABLE_BY_EVENT:
        return False

    try:
        ensure_clickhouse_schema()
        model = _resolve_model(event_type)
        item = db.query(model).filter(model.id == entity_id).first()
        if not item:
            logger.warning(
                "ClickHouse mirror: entity not found %s %s",
                event_type,
                entity_id,
            )
            return False

        event_time = (
            getattr(item, "created_at", None)
            or getattr(item, "started_at", None)
            or datetime.utcnow()
        )
        run_id = getattr(item, "run_id", None)
        if event_type == "agent_run":
            run_id = item.id

        row = [
            str(item.id),
            _product_id(db, event_type, item),
            str(run_id) if run_id else None,
            event_time,
            json.dumps(
                _serialize_model(item),
                default=_json_default,
                ensure_ascii=False,
            ),
            datetime.utcnow(),
        ]

        client = _client()
        client.insert(
            f"telemetry_{TABLE_BY_EVENT[event_type]}",
            [row],
            column_names=[
                "entity_id",
                "product_id",
                "run_id",
                "event_time",
                "payload_json",
                "synced_at",
            ],
        )
        return True
    except Exception:
        logger.exception(
            "ClickHouse mirror failed for %s %s",
            event_type,
            entity_id,
        )
        return False


def clickhouse_status() -> dict:
    try:
        ensure_clickhouse_schema()
        client = _client()
        counts = {}
        for event_type, suffix in TABLE_BY_EVENT.items():
            counts[event_type] = client.query(
                f"SELECT count() FROM telemetry_{suffix}"
            ).result_rows[0][0]

        return {
            "status": "ok",
            "database": os.getenv("CLICKHOUSE_DATABASE", "darial"),
            "counts": counts,
        }
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc)}
