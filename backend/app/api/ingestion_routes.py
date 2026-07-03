from __future__ import annotations

import hashlib
import json
import secrets
import time
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db

router = APIRouter(tags=["Telemetry Ingestion"])

DEFAULT_EVENT_TYPES = [
    "agent_run",
    "llm_call",
    "tool_call",
    "business_outcome",
]

SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "password",
    "passwd",
    "secret",
    "secret_key",
    "token",
    "prompt",
    "response",
    "completion",
    "tool_args",
    "tool_arguments",
    "env",
    "environment_variables",
}

MAX_PAYLOAD_BYTES = 64 * 1024
_rate_limit_state: dict[str, tuple[int, float]] = {}


def ensure_tables(db: Session) -> None:
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS ingestion_sources (
            id VARCHAR(64) PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            source_type VARCHAR(64) NOT NULL,
            product_id VARCHAR(64),
            environment VARCHAR(32) NOT NULL DEFAULT 'prod',
            status VARCHAR(32) NOT NULL DEFAULT 'active',
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            last_seen_at TIMESTAMP
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS ingestion_api_keys (
            id VARCHAR(64) PRIMARY KEY,
            source_id VARCHAR(64) NOT NULL,
            key_prefix VARCHAR(16) NOT NULL,
            key_hash VARCHAR(128) NOT NULL,
            name VARCHAR(255) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'active',
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            last_used_at TIMESTAMP,
            expires_at TIMESTAMP,
            allowed_event_types JSONB,
            rate_limit_per_minute INTEGER NOT NULL DEFAULT 0,
            rotated_from_key_id VARCHAR(64)
        )
    """))
    db.execute(text("""
        ALTER TABLE ingestion_api_keys
        ADD COLUMN IF NOT EXISTS allowed_event_types JSONB
    """))
    db.execute(text("""
        ALTER TABLE ingestion_api_keys
        ADD COLUMN IF NOT EXISTS rate_limit_per_minute INTEGER NOT NULL DEFAULT 0
    """))
    db.execute(text("""
        ALTER TABLE ingestion_api_keys
        ADD COLUMN IF NOT EXISTS rotated_from_key_id VARCHAR(64)
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS ingestion_events (
            id VARCHAR(64) PRIMARY KEY,
            source_id VARCHAR(64) NOT NULL,
            event_id VARCHAR(255) NOT NULL,
            event_type VARCHAR(64) NOT NULL,
            product_id VARCHAR(64),
            agent_name VARCHAR(255),
            trace_id VARCHAR(255),
            payload_json JSONB NOT NULL,
            received_at TIMESTAMP NOT NULL DEFAULT NOW(),
            processed_at TIMESTAMP,
            status VARCHAR(32) NOT NULL DEFAULT 'accepted',
            error_message TEXT,
            UNIQUE(source_id, event_id)
        )
    """))
    db.commit()


def hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sanitize_telemetry(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in SENSITIVE_KEYS:
                result[str(key)] = "[REDACTED]"
            else:
                result[str(key)] = sanitize_telemetry(item)
        return result
    if isinstance(value, list):
        return [sanitize_telemetry(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_telemetry(item) for item in value]
    if isinstance(value, str) and len(value) > 4096:
        return value[:4096] + "...[TRUNCATED]"
    return value


def validate_payload_size(payload: dict[str, Any]) -> None:
    size = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    if size > MAX_PAYLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Telemetry payload is too large",
        )


def verify_api_key(db: Session, authorization: str | None) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer API key")

    raw_key = authorization.removeprefix("Bearer ").strip()
    if not raw_key.startswith("dr_"):
        raise HTTPException(status_code=401, detail="Invalid API key")

    row = db.execute(
        text("""
            SELECT
                k.id,
                k.source_id,
                k.status,
                k.expires_at,
                k.allowed_event_types,
                k.rate_limit_per_minute,
                s.product_id,
                s.environment,
                s.status AS source_status,
                s.name AS source_name
            FROM ingestion_api_keys k
            JOIN ingestion_sources s ON s.id = k.source_id
            WHERE k.key_hash = :key_hash
            LIMIT 1
        """),
        {"key_hash": hash_key(raw_key)},
    ).mappings().first()

    if not row or row["status"] != "active" or row["source_status"] != "active":
        raise HTTPException(status_code=401, detail="Inactive API key")
    if row["expires_at"] and row["expires_at"] < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Expired API key")

    db.execute(
        text("UPDATE ingestion_api_keys SET last_used_at=NOW() WHERE id=:id"),
        {"id": row["id"]},
    )
    db.execute(
        text("UPDATE ingestion_sources SET last_seen_at=NOW() WHERE id=:id"),
        {"id": row["source_id"]},
    )
    db.commit()

    identity = dict(row)
    if isinstance(identity.get("allowed_event_types"), str):
        identity["allowed_event_types"] = json.loads(
            identity["allowed_event_types"]
        )
    return identity


def enforce_rate_limit(identity: dict[str, Any]) -> None:
    limit = int(identity.get("rate_limit_per_minute") or 0)
    if limit <= 0:
        return

    key_id = str(identity["id"])
    now = time.monotonic()
    count, started_at = _rate_limit_state.get(key_id, (0, now))

    if now - started_at >= 60:
        count, started_at = 0, now

    if count >= limit:
        raise HTTPException(
            status_code=429,
            detail="Telemetry rate limit exceeded",
        )

    _rate_limit_state[key_id] = (count + 1, started_at)


class SourceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    source_type: str = "python_sdk"
    product_id: str | None = None
    environment: str = "prod"
    metadata: dict[str, Any] = Field(default_factory=dict)


class KeyCreate(BaseModel):
    name: str = "default"
    expires_at: datetime | None = None
    allowed_event_types: list[str] = Field(
        default_factory=lambda: list(DEFAULT_EVENT_TYPES)
    )
    rate_limit_per_minute: int = Field(default=0, ge=0, le=100000)


class TelemetryEvent(BaseModel):
    event_id: str = Field(min_length=2, max_length=255)
    event_type: str = Field(min_length=2, max_length=64)
    product_id: str | None = None
    agent_name: str | None = None
    trace_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class TelemetryBatch(BaseModel):
    events: list[TelemetryEvent] = Field(min_length=1, max_length=500)


def resolve_event(
    identity: dict[str, Any],
    event: TelemetryEvent,
) -> tuple[str | None, dict[str, Any]]:
    source_product = identity.get("product_id")

    if (
        source_product
        and event.product_id
        and str(event.product_id) != str(source_product)
    ):
        raise HTTPException(
            status_code=403,
            detail="API key cannot submit telemetry for another product",
        )

    allowed = identity.get("allowed_event_types") or DEFAULT_EVENT_TYPES
    if event.event_type not in set(allowed):
        raise HTTPException(
            status_code=403,
            detail="Event type is not allowed for this API key",
        )

    clean_payload = sanitize_telemetry(event.payload)
    validate_payload_size(clean_payload)

    return source_product or event.product_id, clean_payload


@router.post("/ingestion/sources")
def create_source(payload: SourceCreate, db: Session = Depends(get_db)):
    ensure_tables(db)
    source_id = str(uuid.uuid4())
    db.execute(
        text("""
            INSERT INTO ingestion_sources (
                id, name, source_type, product_id, environment, metadata_json
            )
            VALUES (
                :id, :name, :source_type, :product_id, :environment,
                CAST(:metadata AS JSONB)
            )
        """),
        {
            "id": source_id,
            "name": payload.name,
            "source_type": payload.source_type,
            "product_id": payload.product_id,
            "environment": payload.environment,
            "metadata": json.dumps(payload.metadata),
        },
    )
    db.commit()
    return {"id": source_id, **payload.model_dump()}


@router.get("/ingestion/sources")
def list_sources(db: Session = Depends(get_db)):
    ensure_tables(db)
    rows = db.execute(text("""
        SELECT s.*,
               COUNT(DISTINCT k.id) AS key_count,
               COUNT(DISTINCT e.id) AS event_count
        FROM ingestion_sources s
        LEFT JOIN ingestion_api_keys k ON k.source_id = s.id
        LEFT JOIN ingestion_events e ON e.source_id = s.id
        GROUP BY s.id
        ORDER BY s.created_at DESC
    """)).mappings().all()
    return [dict(row) for row in rows]


@router.post("/ingestion/sources/{source_id}/keys")
def create_api_key(
    source_id: str,
    payload: KeyCreate,
    db: Session = Depends(get_db),
):
    ensure_tables(db)
    source = db.execute(
        text("SELECT id FROM ingestion_sources WHERE id=:id"),
        {"id": source_id},
    ).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    raw_key = f"dr_{secrets.token_urlsafe(32)}"
    key_id = str(uuid.uuid4())

    db.execute(
        text("""
            INSERT INTO ingestion_api_keys (
                id, source_id, key_prefix, key_hash, name, expires_at,
                allowed_event_types, rate_limit_per_minute
            )
            VALUES (
                :id, :source_id, :prefix, :key_hash, :name, :expires_at,
                CAST(:allowed_event_types AS JSONB), :rate_limit
            )
        """),
        {
            "id": key_id,
            "source_id": source_id,
            "prefix": raw_key[:12],
            "key_hash": hash_key(raw_key),
            "name": payload.name,
            "expires_at": payload.expires_at,
            "allowed_event_types": json.dumps(payload.allowed_event_types),
            "rate_limit": payload.rate_limit_per_minute,
        },
    )
    db.commit()

    return {
        "id": key_id,
        "source_id": source_id,
        "api_key": raw_key,
        "key_prefix": raw_key[:12],
        "allowed_event_types": payload.allowed_event_types,
        "rate_limit_per_minute": payload.rate_limit_per_minute,
        "warning": "Ключ показывается только один раз.",
    }


@router.post("/ingestion/keys/{key_id}/rotate")
def rotate_api_key(key_id: str, db: Session = Depends(get_db)):
    ensure_tables(db)

    current = db.execute(
        text("""
            SELECT
                source_id,
                name,
                expires_at,
                allowed_event_types,
                rate_limit_per_minute
            FROM ingestion_api_keys
            WHERE id=:id
        """),
        {"id": key_id},
    ).mappings().first()

    if not current:
        raise HTTPException(status_code=404, detail="API key not found")

    raw_key = f"dr_{secrets.token_urlsafe(32)}"
    new_id = str(uuid.uuid4())

    db.execute(
        text("""
            UPDATE ingestion_api_keys
            SET status='revoked'
            WHERE id=:id
        """),
        {"id": key_id},
    )
    db.execute(
        text("""
            INSERT INTO ingestion_api_keys (
                id, source_id, key_prefix, key_hash, name, expires_at,
                allowed_event_types, rate_limit_per_minute,
                rotated_from_key_id
            )
            VALUES (
                :id, :source_id, :prefix, :key_hash, :name, :expires_at,
                CAST(:allowed_event_types AS JSONB), :rate_limit,
                :rotated_from
            )
        """),
        {
            "id": new_id,
            "source_id": current["source_id"],
            "prefix": raw_key[:12],
            "key_hash": hash_key(raw_key),
            "name": current["name"],
            "expires_at": current["expires_at"],
            "allowed_event_types": json.dumps(
                current["allowed_event_types"] or DEFAULT_EVENT_TYPES
            ),
            "rate_limit": current["rate_limit_per_minute"] or 0,
            "rotated_from": key_id,
        },
    )
    db.commit()

    return {
        "id": new_id,
        "source_id": current["source_id"],
        "api_key": raw_key,
        "key_prefix": raw_key[:12],
        "rotated_from_key_id": key_id,
        "warning": "Ключ показывается только один раз.",
    }


@router.patch("/ingestion/keys/{key_id}/revoke")
def revoke_api_key(key_id: str, db: Session = Depends(get_db)):
    ensure_tables(db)
    result = db.execute(
        text("""
            UPDATE ingestion_api_keys
            SET status='revoked'
            WHERE id=:id
            RETURNING id
        """),
        {"id": key_id},
    ).first()
    if not result:
        raise HTTPException(status_code=404, detail="API key not found")
    db.commit()
    return {"id": key_id, "status": "revoked"}


@router.post("/ingestion/events")
def ingest_event(
    payload: TelemetryEvent,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    ensure_tables(db)
    identity = verify_api_key(db, authorization)
    enforce_rate_limit(identity)
    product_id, clean_payload = resolve_event(identity, payload)

    try:
        db.execute(
            text("""
                INSERT INTO ingestion_events (
                    id, source_id, event_id, event_type, product_id,
                    agent_name, trace_id, payload_json
                )
                VALUES (
                    :id, :source_id, :event_id, :event_type, :product_id,
                    :agent_name, :trace_id, CAST(:payload AS JSONB)
                )
            """),
            {
                "id": str(uuid.uuid4()),
                "source_id": identity["source_id"],
                "event_id": payload.event_id,
                "event_type": payload.event_type,
                "product_id": product_id,
                "agent_name": payload.agent_name,
                "trace_id": payload.trace_id,
                "payload": json.dumps(clean_payload),
            },
        )
        db.commit()
        return {
            "accepted": 1,
            "duplicate": 0,
            "accepted_count": 1,
            "rejected_count": 0,
            "request_id": str(uuid.uuid4()),
        }
    except Exception:
        db.rollback()
        existing = db.execute(
            text("""
                SELECT id FROM ingestion_events
                WHERE source_id=:source_id AND event_id=:event_id
            """),
            {
                "source_id": identity["source_id"],
                "event_id": payload.event_id,
            },
        ).first()
        if existing:
            return {
                "accepted": 0,
                "duplicate": 1,
                "accepted_count": 0,
                "rejected_count": 0,
                "request_id": str(uuid.uuid4()),
            }
        raise


@router.post("/ingestion/events/batch")
def ingest_batch(
    payload: TelemetryBatch,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    ensure_tables(db)
    identity = verify_api_key(db, authorization)
    enforce_rate_limit(identity)

    accepted = 0
    duplicate = 0
    rejected = 0
    errors: list[dict[str, str]] = []

    for event in payload.events:
        try:
            product_id, clean_payload = resolve_event(identity, event)
        except HTTPException as exc:
            rejected += 1
            errors.append(
                {"event_id": event.event_id, "detail": str(exc.detail)}
            )
            continue

        existing = db.execute(
            text("""
                SELECT id FROM ingestion_events
                WHERE source_id=:source_id AND event_id=:event_id
            """),
            {
                "source_id": identity["source_id"],
                "event_id": event.event_id,
            },
        ).first()
        if existing:
            duplicate += 1
            continue

        db.execute(
            text("""
                INSERT INTO ingestion_events (
                    id, source_id, event_id, event_type, product_id,
                    agent_name, trace_id, payload_json
                )
                VALUES (
                    :id, :source_id, :event_id, :event_type, :product_id,
                    :agent_name, :trace_id, CAST(:payload AS JSONB)
                )
            """),
            {
                "id": str(uuid.uuid4()),
                "source_id": identity["source_id"],
                "event_id": event.event_id,
                "event_type": event.event_type,
                "product_id": product_id,
                "agent_name": event.agent_name,
                "trace_id": event.trace_id,
                "payload": json.dumps(clean_payload),
            },
        )
        accepted += 1

    db.commit()
    return {
        "accepted": accepted,
        "duplicate": duplicate,
        "rejected": rejected,
        "errors": errors,
        "accepted_count": accepted,
        "rejected_count": rejected,
        "request_id": str(uuid.uuid4()),
    }


@router.get("/ingestion/events")
def list_events(
    source_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    ensure_tables(db)
    if source_id:
        rows = db.execute(
            text("""
                SELECT e.*, s.name AS source_name
                FROM ingestion_events e
                JOIN ingestion_sources s ON s.id=e.source_id
                WHERE e.source_id=:source_id
                ORDER BY e.received_at DESC
                LIMIT :limit
            """),
            {"source_id": source_id, "limit": limit},
        ).mappings().all()
    else:
        rows = db.execute(
            text("""
                SELECT e.*, s.name AS source_name
                FROM ingestion_events e
                JOIN ingestion_sources s ON s.id=e.source_id
                ORDER BY e.received_at DESC
                LIMIT :limit
            """),
            {"limit": limit},
        ).mappings().all()
    return [dict(row) for row in rows]


@router.get("/ingestion/summary")
def ingestion_summary(db: Session = Depends(get_db)):
    ensure_tables(db)
    row = db.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM ingestion_sources) AS sources,
            (SELECT COUNT(*) FROM ingestion_sources WHERE status='active')
                AS active_sources,
            (SELECT COUNT(*) FROM ingestion_api_keys WHERE status='active')
                AS active_keys,
            (SELECT COUNT(*) FROM ingestion_events) AS events,
            (SELECT COUNT(*) FROM ingestion_events
             WHERE received_at >= NOW() - INTERVAL '24 hours') AS events_24h
    """)).mappings().one()
    return dict(row)
