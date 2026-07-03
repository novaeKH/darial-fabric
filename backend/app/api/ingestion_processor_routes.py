from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.api.ingestion_routes import ensure_tables
from app.core.database import get_db
from app.models.base import Agent
from app.models.observability import AgentDeployment, AgentRun, BusinessOutcome, LLMCall, ModelEndpoint, ToolCall
from app.services.economics_service import as_decimal, calculate_llm_cost_breakdown
from app.services.clickhouse_telemetry import clickhouse_status, mirror_entity

router = APIRouter(tags=["Telemetry Processor"])


def _dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _agent(db: Session, name: str | None):
    if not name:
        return None
    return db.query(Agent).filter(func.lower(Agent.name) == name.lower()).first()


def _run(db: Session, trace_id: str | None, payload: dict):
    if payload.get("run_id"):
        found = db.query(AgentRun).filter(AgentRun.id == payload["run_id"]).first()
        if found:
            return found
    if trace_id:
        return db.query(AgentRun).filter(AgentRun.trace_id == trace_id).order_by(AgentRun.created_at.desc()).first()
    return None


def _process_run(db: Session, row: dict) -> str:
    p = row["payload_json"] or {}
    agent = _agent(db, row.get("agent_name"))
    if not agent:
        raise ValueError(f"Агент '{row.get('agent_name')}' не найден")
    product_id = row.get("product_id") or p.get("product_id")
    trace_id = row.get("trace_id") or p.get("trace_id")
    if not product_id or not trace_id:
        raise ValueError("Нужны product_id и trace_id")
    existing = db.query(AgentRun).filter(AgentRun.trace_id == trace_id, AgentRun.agent_id == agent.id).first()
    if existing:
        return existing.id
    dep = db.query(AgentDeployment).filter(
        AgentDeployment.agent_id == agent.id,
        AgentDeployment.product_id == product_id,
    ).first()
    item = AgentRun(
        id=str(uuid.uuid4()), product_id=product_id, agent_id=agent.id,
        deployment_id=dep.id if dep else None, trace_id=trace_id,
        workflow_name=p.get("workflow_name") or row.get("agent_name"),
        environment=p.get("environment") or (dep.environment if dep else "prod"),
        status=p.get("status", "completed"), started_at=_dt(p.get("started_at")) or datetime.utcnow(),
        finished_at=_dt(p.get("finished_at")), latency_ms=p.get("latency_ms"),
        request_count=0, total_cost=0,
        error_type=p.get("error_type"),
        metadata_json={**(p.get("metadata") or {}), "ingestion_event_id": row["event_id"]},
    )
    db.add(item); db.flush(); return item.id


def _process_llm(db: Session, row: dict) -> str:
    p = row["payload_json"] or {}
    run = _run(db, row.get("trace_id"), p)
    if not run:
        raise ValueError("Связанный AgentRun не найден")

    provider = p.get("provider", "unknown")
    model_name = p.get("model_name", "unknown")
    event_time = _dt(p.get("created_at")) or datetime.utcnow()
    endpoint = (
        db.query(ModelEndpoint)
        .filter(
            ModelEndpoint.provider == provider,
            ModelEndpoint.model_name == model_name,
            ModelEndpoint.is_active.is_(True),
            ModelEndpoint.valid_from <= event_time,
            (ModelEndpoint.valid_to.is_(None) | (ModelEndpoint.valid_to >= event_time)),
        )
        .order_by(ModelEndpoint.valid_from.desc())
        .first()
    )

    breakdown = (
        calculate_llm_cost_breakdown(
            input_tokens=int(p.get("input_tokens", 0)),
            output_tokens=int(p.get("output_tokens", 0)),
            cached_tokens=int(p.get("cached_tokens", 0)),
            reasoning_tokens=int(p.get("reasoning_tokens", 0)),
            gpu_seconds=float(p.get("gpu_seconds") or 0),
            endpoint=endpoint,
        )
        if endpoint
        else None
    )
    estimated_cost = breakdown.total_cost if breakdown else as_decimal(0)
    metadata = dict(p.get("metadata") or {})
    metadata["cost_provenance"] = (
        breakdown.as_metadata()
        if breakdown
        else {
            "pricing_method": "not_calculated",
            "reason": "active_tariff_not_found",
            "provider": provider,
            "model": model_name,
        }
    )

    item = LLMCall(
        id=str(uuid.uuid4()),
        run_id=run.id,
        model_endpoint_id=endpoint.id if endpoint else None,
        provider=provider,
        model_name=model_name,
        input_tokens=int(p.get("input_tokens", 0)),
        output_tokens=int(p.get("output_tokens", 0)),
        cached_tokens=int(p.get("cached_tokens", 0)),
        reasoning_tokens=int(p.get("reasoning_tokens", 0)),
        gpu_seconds=p.get("gpu_seconds"),
        latency_ms=p.get("latency_ms"),
        status=p.get("status", "completed"),
        token_source=p.get("token_source", "reported"),
        estimated_cost=estimated_cost,
        metadata_json=metadata,
        created_at=event_time,
    )
    db.add(item)
    run.request_count = int(run.request_count or 0) + 1
    run.total_cost = as_decimal(run.total_cost) + estimated_cost
    db.flush()
    return item.id


def _process_tool(db: Session, row: dict) -> str:
    p = row["payload_json"] or {}
    run = _run(db, row.get("trace_id"), p)
    if not run:
        raise ValueError("Связанный AgentRun не найден")
    reported_cost = as_decimal(p.get("estimated_cost", 0))
    metadata = dict(p.get("metadata") or {})
    metadata["cost_provenance"] = {
        "pricing_method": "reported_by_integration",
        "verified": False,
    }
    item = ToolCall(
        id=str(uuid.uuid4()),
        run_id=run.id,
        tool_name=p.get("tool_name", "unknown"),
        status=p.get("status", "completed"),
        latency_ms=p.get("latency_ms"),
        estimated_cost=reported_cost,
        metadata_json=metadata,
        created_at=_dt(p.get("created_at")) or datetime.utcnow(),
    )
    db.add(item)
    run.total_cost = as_decimal(run.total_cost) + reported_cost
    db.flush()
    return item.id


def _process_outcome(db: Session, row: dict) -> str:
    p = row["payload_json"] or {}; run = _run(db, row.get("trace_id"), p)
    if not run: raise ValueError("Связанный AgentRun не найден")
    item = BusinessOutcome(
        id=str(uuid.uuid4()), run_id=run.id,
        outcome_type=p.get("outcome_type", "completed_task"), success=bool(p.get("success", True)),
        quantity=p.get("quantity", 1), quality_score=p.get("quality_score"),
        human_accepted=p.get("human_accepted"), time_saved_minutes=p.get("time_saved_minutes"),
        estimated_business_value=p.get("estimated_business_value"),
        created_at=_dt(p.get("created_at")) or datetime.utcnow(),
    )
    db.add(item); db.flush(); return item.id


PROCESSORS = {"agent_run": _process_run, "llm_call": _process_llm, "tool_call": _process_tool, "business_outcome": _process_outcome}


@router.post("/ingestion/process")
def process_events(limit: int = Query(200, ge=1, le=1000), db: Session = Depends(get_db)):
    ensure_tables(db)
    rows = db.execute(text("""
        SELECT id, source_id, event_id, event_type, product_id, agent_name, trace_id, payload_json, received_at
        FROM ingestion_events WHERE status='accepted'
        ORDER BY CASE event_type WHEN 'agent_run' THEN 1 WHEN 'llm_call' THEN 2 WHEN 'tool_call' THEN 3 WHEN 'business_outcome' THEN 4 ELSE 10 END, received_at
        LIMIT :limit
    """), {"limit": limit}).mappings().all()
    result = {"selected": len(rows), "processed": 0, "failed": 0, "unsupported": 0, "results": []}
    for raw in rows:
        row = dict(raw); fn = PROCESSORS.get(row["event_type"])
        if not fn:
            db.execute(text("UPDATE ingestion_events SET status='unsupported', error_message=:m WHERE id=:id"), {"id": row["id"], "m": f"Unsupported event_type: {row['event_type']}"}); db.commit(); result["unsupported"] += 1; continue
        try:
            entity_id = fn(db, row)
            db.execute(text("UPDATE ingestion_events SET status='processed', processed_at=NOW(), error_message=NULL WHERE id=:id"), {"id": row["id"]})
            db.commit()
            mirrored = mirror_entity(db, row["event_type"], entity_id)
            result["processed"] += 1
            result["results"].append({
                "event_id": row["event_id"],
                "entity_id": entity_id,
                "status": "processed",
                "clickhouse_mirrored": mirrored,
            })
        except Exception as exc:
            db.rollback(); db.execute(text("UPDATE ingestion_events SET status='failed', error_message=:m WHERE id=:id"), {"id": row["id"], "m": str(exc)[:1000]}); db.commit(); result["failed"] += 1; result["results"].append({"event_id": row["event_id"], "status": "failed", "error": str(exc)})
    return result


@router.post("/ingestion/events/{event_id}/retry")
def retry_event(event_id: str, db: Session = Depends(get_db)):
    ensure_tables(db)
    row = db.execute(text("UPDATE ingestion_events SET status='accepted', processed_at=NULL, error_message=NULL WHERE id=:id RETURNING id"), {"id": event_id}).first()
    if not row: raise HTTPException(status_code=404, detail="Event not found")
    db.commit(); return {"id": event_id, "status": "accepted"}


@router.get("/ingestion/processing-summary")
def summary(db: Session = Depends(get_db)):
    ensure_tables(db)
    rows = db.execute(text("SELECT status, COUNT(*) AS count FROM ingestion_events GROUP BY status")).mappings().all()
    result = {"accepted": 0, "processed": 0, "failed": 0, "unsupported": 0}
    for row in rows: result[row["status"]] = row["count"]
    result["total"] = sum(result.values()); return result

@router.get("/ingestion/clickhouse-status")
def get_clickhouse_status():
    return clickhouse_status()

