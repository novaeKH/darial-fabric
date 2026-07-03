from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.base import Agent
from app.models.observability import (
    AIProduct,
    AgentRun,
    PolicyViolation,
    ViolationStatus,
)

router = APIRouter(tags=["AI Governance"])


def value_of(value: Any) -> Any:
    return getattr(value, "value", value)


class ViolationStatusPayload(BaseModel):
    status: str


@router.get("/observability/violations")
def list_violations(
    status: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    product_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(PolicyViolation)

    if status:
        query = query.filter(PolicyViolation.status == status)
    if severity:
        query = query.filter(PolicyViolation.severity == severity)
    if product_id:
        query = query.filter(PolicyViolation.product_id == product_id)

    items = (
        query.order_by(PolicyViolation.detected_at.desc())
        .limit(limit)
        .all()
    )

    products = {
        item.id: item
        for item in db.query(AIProduct)
        .filter(AIProduct.id.in_([x.product_id for x in items if x.product_id]))
        .all()
    }
    runs = {
        item.id: item
        for item in db.query(AgentRun)
        .filter(AgentRun.id.in_([x.run_id for x in items if x.run_id]))
        .all()
    }
    agents = {
        item.id: item
        for item in db.query(Agent)
        .filter(Agent.id.in_([x.agent_id for x in items if x.agent_id]))
        .all()
    }

    result = []
    for item in items:
        product = products.get(item.product_id)
        run = runs.get(item.run_id)
        agent = agents.get(item.agent_id)

        result.append(
            {
                "id": item.id,
                "product_id": item.product_id,
                "product_name": getattr(product, "name", None),
                "agent_id": item.agent_id,
                "agent_name": getattr(agent, "name", None),
                "run_id": item.run_id,
                "trace_id": getattr(run, "trace_id", None),
                "workflow_name": getattr(run, "workflow_name", None),
                "policy_code": item.policy_code,
                "severity": value_of(item.severity),
                "description": item.description,
                "status": value_of(item.status),
                "details": item.details,
                "detected_at": item.detected_at,
                "resolved_at": item.resolved_at,
            }
        )

    return result


@router.get("/observability/violations/summary")
def violations_summary(db: Session = Depends(get_db)):
    items = db.query(PolicyViolation).all()

    def count(**conditions):
        total = 0
        for item in items:
            ok = True
            for key, expected in conditions.items():
                if value_of(getattr(item, key)) != expected:
                    ok = False
                    break
            if ok:
                total += 1
        return total

    return {
        "total": len(items),
        "open": count(status="open"),
        "resolved": count(status="resolved"),
        "critical": count(severity="critical"),
        "warning": count(severity="warning"),
        "info": count(severity="info"),
    }


@router.patch("/observability/violations/{violation_id}/status")
def update_violation_status(
    violation_id: str,
    payload: ViolationStatusPayload,
    db: Session = Depends(get_db),
):
    item = (
        db.query(PolicyViolation)
        .filter(PolicyViolation.id == violation_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Violation not found")

    allowed = {"open", "acknowledged", "resolved"}
    if payload.status not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"Allowed statuses: {sorted(allowed)}",
        )

    item.status = payload.status
    if payload.status == "resolved":
        item.resolved_at = datetime.utcnow()
    else:
        item.resolved_at = None

    db.commit()
    db.refresh(item)

    return {
        "id": item.id,
        "status": value_of(item.status),
        "resolved_at": item.resolved_at,
    }
