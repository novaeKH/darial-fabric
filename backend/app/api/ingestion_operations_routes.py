from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.ingestion_routes import ensure_tables

router = APIRouter(tags=["Ingestion Operations"])


def ensure_columns(db: Session) -> None:
    ensure_tables(db)
    db.execute(text("""
        ALTER TABLE ingestion_events
        ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0
    """))
    db.execute(text("""
        ALTER TABLE ingestion_events
        ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMP
    """))
    db.execute(text("""
        ALTER TABLE ingestion_events
        ADD COLUMN IF NOT EXISTS locked_at TIMESTAMP
    """))
    db.execute(text("""
        ALTER TABLE ingestion_events
        ADD COLUMN IF NOT EXISTS locked_by VARCHAR(128)
    """))
    db.commit()


@router.get("/ingestion/operations-summary")
def operations_summary(db: Session = Depends(get_db)):
    ensure_columns(db)
    rows = db.execute(
        text("""
            SELECT status, COUNT(*) AS count
            FROM ingestion_events
            GROUP BY status
        """)
    ).mappings().all()

    result = {
        "accepted": 0,
        "processing": 0,
        "retry": 0,
        "processed": 0,
        "failed": 0,
        "dead_letter": 0,
        "unsupported": 0,
    }
    for row in rows:
        result[row["status"]] = row["count"]

    result["pending"] = (
        result["accepted"] + result["processing"] + result["retry"]
    )
    result["total"] = sum(
        value for key, value in result.items()
        if key not in {"pending", "total"}
    )
    return result


@router.get("/ingestion/dead-letter")
def list_dead_letter(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    ensure_columns(db)
    rows = db.execute(
        text("""
            SELECT e.id, e.event_id, e.event_type, e.product_id,
                   e.agent_name, e.trace_id, e.retry_count,
                   e.error_message, e.received_at, e.processed_at,
                   s.name AS source_name
            FROM ingestion_events e
            JOIN ingestion_sources s ON s.id=e.source_id
            WHERE e.status='dead_letter'
            ORDER BY e.received_at DESC
            LIMIT :limit
        """),
        {"limit": limit},
    ).mappings().all()
    return [dict(row) for row in rows]


@router.post("/ingestion/events/{event_id}/requeue")
def requeue_dead_letter(event_id: str, db: Session = Depends(get_db)):
    ensure_columns(db)
    result = db.execute(
        text("""
            UPDATE ingestion_events
            SET status='accepted',
                retry_count=0,
                error_message=NULL,
                next_retry_at=NULL,
                locked_at=NULL,
                locked_by=NULL
            WHERE id=:id
              AND status IN ('dead_letter', 'failed', 'unsupported')
            RETURNING id
        """),
        {"id": event_id},
    ).first()

    if not result:
        raise HTTPException(
            status_code=404,
            detail="Event not found or cannot be requeued",
        )

    db.commit()
    return {"id": event_id, "status": "accepted"}


@router.post("/ingestion/requeue-all")
def requeue_all_dead_letters(db: Session = Depends(get_db)):
    ensure_columns(db)
    count = db.execute(
        text("""
            UPDATE ingestion_events
            SET status='accepted',
                retry_count=0,
                error_message=NULL,
                next_retry_at=NULL,
                locked_at=NULL,
                locked_by=NULL
            WHERE status='dead_letter'
            RETURNING id
        """)
    ).all()
    db.commit()
    return {"requeued": len(count)}
