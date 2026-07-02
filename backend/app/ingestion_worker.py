from __future__ import annotations

import os
import time
from datetime import datetime

from sqlalchemy import text

from app.core.database import SessionLocal
from app.api.ingestion_routes import ensure_tables
from app.api.ingestion_processor_routes import PROCESSORS


POLL_INTERVAL_SECONDS = int(os.getenv("INGESTION_POLL_INTERVAL_SECONDS", "5"))
BATCH_SIZE = int(os.getenv("INGESTION_BATCH_SIZE", "200"))
MAX_RETRIES = int(os.getenv("INGESTION_MAX_RETRIES", "3"))


def ensure_worker_columns(db) -> None:
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


def claim_events(db, worker_id: str):
    rows = db.execute(
        text("""
            WITH candidates AS (
                SELECT id
                FROM ingestion_events
                WHERE status IN ('accepted', 'retry')
                  AND (next_retry_at IS NULL OR next_retry_at <= NOW())
                  AND (locked_at IS NULL OR locked_at < NOW() - INTERVAL '10 minutes')
                ORDER BY
                    CASE event_type
                        WHEN 'agent_run' THEN 1
                        WHEN 'llm_call' THEN 2
                        WHEN 'tool_call' THEN 3
                        WHEN 'business_outcome' THEN 4
                        ELSE 10
                    END,
                    received_at
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
            )
            UPDATE ingestion_events e
            SET locked_at = NOW(),
                locked_by = :worker_id,
                status = 'processing'
            FROM candidates c
            WHERE e.id = c.id
            RETURNING e.id, e.source_id, e.event_id, e.event_type,
                      e.product_id, e.agent_name, e.trace_id,
                      e.payload_json, e.retry_count, e.received_at
        """),
        {"limit": BATCH_SIZE, "worker_id": worker_id},
    ).mappings().all()
    db.commit()
    return [dict(row) for row in rows]


def mark_processed(db, event_id: str) -> None:
    db.execute(
        text("""
            UPDATE ingestion_events
            SET status='processed',
                processed_at=NOW(),
                error_message=NULL,
                locked_at=NULL,
                locked_by=NULL,
                next_retry_at=NULL
            WHERE id=:id
        """),
        {"id": event_id},
    )
    db.commit()


def mark_unsupported(db, event_id: str, event_type: str) -> None:
    db.execute(
        text("""
            UPDATE ingestion_events
            SET status='unsupported',
                error_message=:message,
                locked_at=NULL,
                locked_by=NULL
            WHERE id=:id
        """),
        {
            "id": event_id,
            "message": f"Unsupported event_type: {event_type}",
        },
    )
    db.commit()


def mark_failed(db, row: dict, exc: Exception) -> None:
    retry_count = int(row.get("retry_count") or 0) + 1

    if retry_count >= MAX_RETRIES:
        status = "dead_letter"
        next_retry_sql = "NULL"
    else:
        status = "retry"
        delay_seconds = min(60 * (2 ** (retry_count - 1)), 900)
        next_retry_sql = f"NOW() + INTERVAL '{delay_seconds} seconds'"

    db.execute(
        text(f"""
            UPDATE ingestion_events
            SET status=:status,
                retry_count=:retry_count,
                error_message=:message,
                next_retry_at={next_retry_sql},
                locked_at=NULL,
                locked_by=NULL
            WHERE id=:id
        """),
        {
            "id": row["id"],
            "status": status,
            "retry_count": retry_count,
            "message": str(exc)[:1000],
        },
    )
    db.commit()


def process_once(worker_id: str) -> dict:
    with SessionLocal() as db:
        ensure_worker_columns(db)
        rows = claim_events(db, worker_id)

    processed = 0
    failed = 0
    unsupported = 0

    for row in rows:
        processor = PROCESSORS.get(row["event_type"])

        with SessionLocal() as db:
            if not processor:
                mark_unsupported(db, row["id"], row["event_type"])
                unsupported += 1
                continue

            try:
                processor(db, row)
                db.commit()
                mark_processed(db, row["id"])
                processed += 1
            except Exception as exc:
                db.rollback()
                mark_failed(db, row, exc)
                failed += 1

    return {
        "selected": len(rows),
        "processed": processed,
        "failed": failed,
        "unsupported": unsupported,
    }


def main() -> None:
    worker_id = f"ingestion-worker-{os.getpid()}"
    print(
        f"[{datetime.utcnow().isoformat()}] Worker started: {worker_id}, "
        f"poll={POLL_INTERVAL_SECONDS}s, batch={BATCH_SIZE}, retries={MAX_RETRIES}",
        flush=True,
    )

    while True:
        try:
            result = process_once(worker_id)
            if result["selected"]:
                print(
                    f"[{datetime.utcnow().isoformat()}] "
                    f"selected={result['selected']} "
                    f"processed={result['processed']} "
                    f"failed={result['failed']} "
                    f"unsupported={result['unsupported']}",
                    flush=True,
                )
        except Exception as exc:
            print(
                f"[{datetime.utcnow().isoformat()}] Worker loop error: {exc}",
                flush=True,
            )

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
