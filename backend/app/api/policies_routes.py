from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.observability import (
    AgentRun,
    BusinessOutcome,
    LLMCall,
    PolicyViolation,
    ToolCall,
    ViolationStatus,
)

router = APIRouter(tags=["AI Policies"])


def ensure_table(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS governance_policies (
                id VARCHAR(64) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                code VARCHAR(128) NOT NULL UNIQUE,
                description TEXT,
                scope_type VARCHAR(32) NOT NULL DEFAULT 'organization',
                scope_id VARCHAR(64),
                rule_type VARCHAR(64) NOT NULL,
                config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                severity VARCHAR(32) NOT NULL DEFAULT 'warning',
                mode VARCHAR(32) NOT NULL DEFAULT 'monitor',
                is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    db.commit()


def row_to_dict(row) -> dict[str, Any]:
    mapping = row._mapping
    config = mapping["config_json"]
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except json.JSONDecodeError:
            config = {}
    return {
        "id": mapping["id"],
        "name": mapping["name"],
        "code": mapping["code"],
        "description": mapping["description"],
        "scope_type": mapping["scope_type"],
        "scope_id": mapping["scope_id"],
        "rule_type": mapping["rule_type"],
        "config": config or {},
        "severity": mapping["severity"],
        "mode": mapping["mode"],
        "is_enabled": bool(mapping["is_enabled"]),
        "created_at": mapping["created_at"],
        "updated_at": mapping["updated_at"],
    }


class PolicyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    code: str = Field(min_length=2, max_length=128)
    description: str | None = None
    scope_type: str = "organization"
    scope_id: str | None = None
    rule_type: str
    config: dict[str, Any] = Field(default_factory=dict)
    severity: str = "warning"
    mode: str = "monitor"
    is_enabled: bool = True


class PolicyUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    scope_type: str | None = None
    scope_id: str | None = None
    rule_type: str | None = None
    config: dict[str, Any] | None = None
    severity: str | None = None
    mode: str | None = None
    is_enabled: bool | None = None


@router.get("/observability/policies")
def list_policies(db: Session = Depends(get_db)):
    ensure_table(db)
    rows = db.execute(
        text(
            """
            SELECT id, name, code, description, scope_type, scope_id,
                   rule_type, config_json, severity, mode, is_enabled,
                   created_at, updated_at
            FROM governance_policies
            ORDER BY is_enabled DESC, severity, name
            """
        )
    ).all()
    return [row_to_dict(row) for row in rows]


@router.post("/observability/policies")
def create_policy(payload: PolicyCreate, db: Session = Depends(get_db)):
    ensure_table(db)

    allowed_rule_types = {
        "max_run_cost",
        "max_latency_ms",
        "require_outcome",
        "allowed_models",
        "prohibited_tools",
        "max_retries",
    }
    if payload.rule_type not in allowed_rule_types:
        raise HTTPException(status_code=422, detail="Unsupported rule_type")
    if payload.severity not in {"info", "warning", "critical"}:
        raise HTTPException(status_code=422, detail="Unsupported severity")
    if payload.mode not in {"monitor", "block"}:
        raise HTTPException(status_code=422, detail="Unsupported mode")
    if payload.scope_type not in {"organization", "product"}:
        raise HTTPException(status_code=422, detail="Unsupported scope_type")

    policy_id = str(uuid.uuid4())
    try:
        db.execute(
            text(
                """
                INSERT INTO governance_policies (
                    id, name, code, description, scope_type, scope_id,
                    rule_type, config_json, severity, mode, is_enabled
                )
                VALUES (
                    :id, :name, :code, :description, :scope_type, :scope_id,
                    :rule_type, CAST(:config_json AS JSONB), :severity, :mode,
                    :is_enabled
                )
                """
            ),
            {
                "id": policy_id,
                "name": payload.name,
                "code": payload.code.upper().replace(" ", "_"),
                "description": payload.description,
                "scope_type": payload.scope_type,
                "scope_id": payload.scope_id,
                "rule_type": payload.rule_type,
                "config_json": json.dumps(payload.config),
                "severity": payload.severity,
                "mode": payload.mode,
                "is_enabled": payload.is_enabled,
            },
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Policy code already exists") from exc

    row = db.execute(
        text("SELECT * FROM governance_policies WHERE id = :id"),
        {"id": policy_id},
    ).first()
    return row_to_dict(row)


@router.patch("/observability/policies/{policy_id}")
def update_policy(
    policy_id: str,
    payload: PolicyUpdate,
    db: Session = Depends(get_db),
):
    ensure_table(db)
    current = db.execute(
        text("SELECT * FROM governance_policies WHERE id = :id"),
        {"id": policy_id},
    ).first()
    if not current:
        raise HTTPException(status_code=404, detail="Policy not found")

    data = row_to_dict(current)
    updates = payload.model_dump(exclude_unset=True)
    data.update(updates)

    db.execute(
        text(
            """
            UPDATE governance_policies
            SET name = :name,
                description = :description,
                scope_type = :scope_type,
                scope_id = :scope_id,
                rule_type = :rule_type,
                config_json = CAST(:config_json AS JSONB),
                severity = :severity,
                mode = :mode,
                is_enabled = :is_enabled,
                updated_at = NOW()
            WHERE id = :id
            """
        ),
        {
            "id": policy_id,
            "name": data["name"],
            "description": data["description"],
            "scope_type": data["scope_type"],
            "scope_id": data["scope_id"],
            "rule_type": data["rule_type"],
            "config_json": json.dumps(data["config"]),
            "severity": data["severity"],
            "mode": data["mode"],
            "is_enabled": data["is_enabled"],
        },
    )
    db.commit()

    row = db.execute(
        text("SELECT * FROM governance_policies WHERE id = :id"),
        {"id": policy_id},
    ).first()
    return row_to_dict(row)


def policy_applies(policy: dict[str, Any], run: AgentRun) -> bool:
    if policy["scope_type"] == "organization":
        return True
    return policy["scope_type"] == "product" and policy["scope_id"] == run.product_id


def existing_violation(
    db: Session,
    run_id: str,
    policy_code: str,
) -> bool:
    return (
        db.query(PolicyViolation)
        .filter(
            PolicyViolation.run_id == run_id,
            PolicyViolation.policy_code == policy_code,
            PolicyViolation.status != ViolationStatus.resolved,
        )
        .first()
        is not None
    )


@router.post("/observability/policies/evaluate")
def evaluate_policies(db: Session = Depends(get_db)):
    ensure_table(db)
    policy_rows = db.execute(
        text(
            """
            SELECT * FROM governance_policies
            WHERE is_enabled = TRUE
            ORDER BY created_at
            """
        )
    ).all()
    policies = [row_to_dict(row) for row in policy_rows]
    runs = (
        db.query(AgentRun)
        .order_by(AgentRun.started_at.desc())
        .limit(300)
        .all()
    )

    created = []

    for run in runs:
        llm_calls = db.query(LLMCall).filter(LLMCall.run_id == run.id).all()
        tool_calls = db.query(ToolCall).filter(ToolCall.run_id == run.id).all()
        outcomes = (
            db.query(BusinessOutcome)
            .filter(BusinessOutcome.run_id == run.id)
            .all()
        )

        for policy in policies:
            if not policy_applies(policy, run):
                continue
            if existing_violation(db, run.id, policy["code"]):
                continue

            config = policy["config"] or {}
            violated = False
            reason = ""

            if policy["rule_type"] == "max_run_cost":
                limit = float(config.get("limit", 0))
                actual = float(run.total_cost or 0)
                violated = limit > 0 and actual > limit
                reason = f"Стоимость run {actual:.2f} превышает лимит {limit:.2f}."

            elif policy["rule_type"] == "max_latency_ms":
                limit = int(config.get("limit", 0))
                actual = int(run.latency_ms or 0)
                violated = limit > 0 and actual > limit
                reason = f"Latency {actual} мс превышает лимит {limit} мс."

            elif policy["rule_type"] == "require_outcome":
                violated = len(outcomes) == 0
                reason = "Run завершён без зарегистрированного business outcome."

            elif policy["rule_type"] == "allowed_models":
                allowed = set(config.get("models", []))
                used = {call.model_name for call in llm_calls if call.model_name}
                forbidden = sorted(used - allowed)
                violated = bool(allowed and forbidden)
                reason = f"Использованы недопустимые модели: {', '.join(forbidden)}."

            elif policy["rule_type"] == "prohibited_tools":
                prohibited = set(config.get("tools", []))
                used = {call.tool_name for call in tool_calls if call.tool_name}
                matched = sorted(used & prohibited)
                violated = bool(matched)
                reason = f"Использованы запрещённые инструменты: {', '.join(matched)}."

            elif policy["rule_type"] == "max_retries":
                limit = int(config.get("limit", 0))
                metadata = run.metadata_json or {}
                retries = int(metadata.get("retry_count", 0))
                violated = retries > limit
                reason = f"Число retries {retries} превышает лимит {limit}."

            if not violated:
                continue

            item = PolicyViolation(
                product_id=run.product_id,
                agent_id=run.agent_id,
                run_id=run.id,
                policy_code=policy["code"],
                severity=policy["severity"],
                description=reason,
                status=ViolationStatus.open,
                details={
                    "policy_id": policy["id"],
                    "policy_name": policy["name"],
                    "rule_type": policy["rule_type"],
                    "mode": policy["mode"],
                    "config": config,
                },
                detected_at=datetime.utcnow(),
            )
            db.add(item)
            created.append(
                {
                    "run_id": run.id,
                    "policy_code": policy["code"],
                    "severity": policy["severity"],
                    "mode": policy["mode"],
                }
            )

    db.commit()
    return {
        "checked_runs": len(runs),
        "active_policies": len(policies),
        "created": len(created),
        "violations": created,
    }
