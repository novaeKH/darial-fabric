from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db

router = APIRouter(tags=["Telemetry Ingestion"])


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
            expires_at TIMESTAMP
        )
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


def verify_api_key(db: Session, authorization: str | None) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer API key")

    raw_key = authorization.removeprefix("Bearer ").strip()
    if not raw_key.startswith("dr_"):
        raise HTTPException(status_code=401, detail="Invalid API key")

    row = db.execute(
        text("""
            SELECT k.id, k.source_id, k.status, k.expires_at, s.product_id,
                   s.environment, s.status AS source_status, s.name AS source_name
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
    return dict(row)


class SourceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    source_type: str = "python_sdk"
    product_id: str | None = None
    environment: str = "prod"
    metadata: dict[str, Any] = Field(default_factory=dict)


class KeyCreate(BaseModel):
    name: str = "default"
    expires_at: datetime | None = None


class TelemetryEvent(BaseModel):
    event_id: str = Field(min_length=2, max_length=255)
    event_type: str = Field(min_length=2, max_length=64)
    product_id: str | None = None
    agent_name: str | None = None
    trace_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class TelemetryBatch(BaseModel):
    events: list[TelemetryEvent] = Field(min_length=1, max_length=500)


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
                id, source_id, key_prefix, key_hash, name, expires_at
            )
            VALUES (
                :id, :source_id, :prefix, :key_hash, :name, :expires_at
            )
        """),
        {
            "id": key_id,
            "source_id": source_id,
            "prefix": raw_key[:12],
            "key_hash": hash_key(raw_key),
            "name": payload.name,
            "expires_at": payload.expires_at,
        },
    )
    db.commit()
    return {
        "id": key_id,
        "source_id": source_id,
        "api_key": raw_key,
        "key_prefix": raw_key[:12],
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
    product_id = payload.product_id or identity["product_id"]

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
                "payload": json.dumps(payload.payload),
            },
        )
        db.commit()
        return {"accepted": 1, "duplicate": 0}
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
            return {"accepted": 0, "duplicate": 1}
        raise


@router.post("/ingestion/events/batch")
def ingest_batch(
    payload: TelemetryBatch,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    ensure_tables(db)
    identity = verify_api_key(db, authorization)
    accepted = 0
    duplicate = 0

    for event in payload.events:
        product_id = event.product_id or identity["product_id"]
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
                "payload": json.dumps(event.payload),
            },
        )
        accepted += 1

    db.commit()
    return {"accepted": accepted, "duplicate": duplicate}


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
            (SELECT COUNT(*) FROM ingestion_sources WHERE status='active') AS active_sources,
            (SELECT COUNT(*) FROM ingestion_api_keys WHERE status='active') AS active_keys,
            (SELECT COUNT(*) FROM ingestion_events) AS events,
            (SELECT COUNT(*) FROM ingestion_events
             WHERE received_at >= NOW() - INTERVAL '24 hours') AS events_24h
    """)).mappings().one()
    return dict(row)
