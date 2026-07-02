from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

import yaml
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db

router = APIRouter(tags=["Enterprise Policy Management"])


def ensure_tables(db: Session) -> None:
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS governance_policy_versions (
            id VARCHAR(64) PRIMARY KEY,
            policy_id VARCHAR(64) NOT NULL,
            version INTEGER NOT NULL,
            snapshot_json JSONB NOT NULL,
            changed_by VARCHAR(255),
            change_note TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS governance_policy_audit (
            id VARCHAR(64) PRIMARY KEY,
            policy_id VARCHAR(64),
            action VARCHAR(64) NOT NULL,
            actor VARCHAR(255),
            details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """))
    db.commit()


def parse_document(content: bytes, filename: str) -> Any:
    text_value = content.decode("utf-8")
    suffix = filename.lower()
    try:
        if suffix.endswith((".yaml", ".yml")):
            return yaml.safe_load(text_value)
        return json.loads(text_value)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Не удалось разобрать JSON/YAML") from exc


def normalized_policy(item: dict[str, Any]) -> dict[str, Any]:
    scope = item.get("scope") or {}
    rule = item.get("rule") or {}
    return {
        "name": item.get("name") or item.get("code") or "Imported policy",
        "code": str(item.get("code") or "").upper().replace(" ", "_"),
        "description": item.get("description"),
        "scope_type": item.get("scope_type") or scope.get("type") or "organization",
        "scope_id": item.get("scope_id") or scope.get("product_id"),
        "rule_type": item.get("rule_type") or rule.get("type") or "custom_condition",
        "config": item.get("config") or {
            key: value for key, value in rule.items() if key != "type"
        },
        "severity": item.get("severity", "warning"),
        "mode": item.get("mode", "monitor"),
        "is_enabled": item.get("is_enabled", True),
    }


def create_version(
    db: Session,
    policy_id: str,
    snapshot: dict[str, Any],
    actor: str,
    note: str,
) -> None:
    current = db.execute(
        text("""
            SELECT COALESCE(MAX(version), 0) + 1
            FROM governance_policy_versions
            WHERE policy_id = :policy_id
        """),
        {"policy_id": policy_id},
    ).scalar_one()

    db.execute(
        text("""
            INSERT INTO governance_policy_versions (
                id, policy_id, version, snapshot_json, changed_by, change_note
            )
            VALUES (
                :id, :policy_id, :version, CAST(:snapshot AS JSONB), :actor, :note
            )
        """),
        {
            "id": str(uuid.uuid4()),
            "policy_id": policy_id,
            "version": current,
            "snapshot": json.dumps(snapshot),
            "actor": actor,
            "note": note,
        },
    )


def write_audit(
    db: Session,
    policy_id: str | None,
    action: str,
    actor: str,
    details: dict[str, Any],
) -> None:
    db.execute(
        text("""
            INSERT INTO governance_policy_audit (
                id, policy_id, action, actor, details_json
            )
            VALUES (
                :id, :policy_id, :action, :actor, CAST(:details AS JSONB)
            )
        """),
        {
            "id": str(uuid.uuid4()),
            "policy_id": policy_id,
            "action": action,
            "actor": actor,
            "details": json.dumps(details),
        },
    )


class ImportOptions(BaseModel):
    actor: str = "admin@darial.local"
    replace_existing: bool = True


class CustomPolicyPayload(BaseModel):
    name: str = Field(min_length=2)
    code: str = Field(min_length=2)
    description: str | None = None
    scope_type: str = "organization"
    scope_id: str | None = None
    field: str
    operator: str
    value: Any
    conditions: dict[str, Any] = Field(default_factory=dict)
    severity: str = "warning"
    mode: str = "monitor"
    actor: str = "admin@darial.local"


@router.post("/observability/policies/import")
async def import_policies(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    ensure_tables(db)
    payload = parse_document(await file.read(), file.filename or "policies.json")
    items = payload if isinstance(payload, list) else payload.get("policies", [payload])

    imported = []
    for raw in items:
        policy = normalized_policy(raw)
        if not policy["code"]:
            raise HTTPException(status_code=422, detail="У политики отсутствует code")

        existing = db.execute(
            text("SELECT * FROM governance_policies WHERE code = :code"),
            {"code": policy["code"]},
        ).mappings().first()

        if existing:
            policy_id = existing["id"]
            snapshot = dict(existing)
            if isinstance(snapshot.get("config_json"), str):
                snapshot["config_json"] = json.loads(snapshot["config_json"])
            create_version(
                db,
                policy_id,
                snapshot,
                "import",
                f"Перед импортом {file.filename}",
            )
            db.execute(
                text("""
                    UPDATE governance_policies
                    SET name=:name,
                        description=:description,
                        scope_type=:scope_type,
                        scope_id=:scope_id,
                        rule_type=:rule_type,
                        config_json=CAST(:config AS JSONB),
                        severity=:severity,
                        mode=:mode,
                        is_enabled=:is_enabled,
                        updated_at=NOW()
                    WHERE id=:id
                """),
                {
                    "id": policy_id,
                    "name": policy["name"],
                    "description": policy["description"],
                    "scope_type": policy["scope_type"],
                    "scope_id": policy["scope_id"],
                    "rule_type": policy["rule_type"],
                    "config": json.dumps(policy["config"]),
                    "severity": policy["severity"],
                    "mode": policy["mode"],
                    "is_enabled": policy["is_enabled"],
                },
            )
            action = "import_update"
        else:
            policy_id = str(uuid.uuid4())
            db.execute(
                text("""
                    INSERT INTO governance_policies (
                        id, name, code, description, scope_type, scope_id,
                        rule_type, config_json, severity, mode, is_enabled
                    )
                    VALUES (
                        :id, :name, :code, :description, :scope_type, :scope_id,
                        :rule_type, CAST(:config AS JSONB), :severity, :mode, :is_enabled
                    )
                """),
                {
                    "id": policy_id,
                    "name": policy["name"],
                    "code": policy["code"],
                    "description": policy["description"],
                    "scope_type": policy["scope_type"],
                    "scope_id": policy["scope_id"],
                    "rule_type": policy["rule_type"],
                    "config": json.dumps(policy["config"]),
                    "severity": policy["severity"],
                    "mode": policy["mode"],
                    "is_enabled": policy["is_enabled"],
                },
            )
            action = "import_create"

        write_audit(
            db,
            policy_id,
            action,
            "import",
            {"filename": file.filename, "code": policy["code"]},
        )
        imported.append({"id": policy_id, "code": policy["code"], "action": action})

    db.commit()
    return {"imported": len(imported), "items": imported}


@router.get("/observability/policies/export")
def export_policies(
    format: str = "yaml",
    db: Session = Depends(get_db),
):
    ensure_tables(db)
    rows = db.execute(
        text("""
            SELECT name, code, description, scope_type, scope_id,
                   rule_type, config_json, severity, mode, is_enabled
            FROM governance_policies
            ORDER BY code
        """)
    ).mappings().all()

    policies = []
    for row in rows:
        config = row["config_json"]
        if isinstance(config, str):
            config = json.loads(config)
        policies.append({
            "name": row["name"],
            "code": row["code"],
            "description": row["description"],
            "scope": {
                "type": row["scope_type"],
                "product_id": row["scope_id"],
            },
            "rule": {
                "type": row["rule_type"],
                **(config or {}),
            },
            "severity": row["severity"],
            "mode": row["mode"],
            "is_enabled": row["is_enabled"],
        })

    document = {"version": 1, "policies": policies}
    if format == "json":
        return PlainTextResponse(
            json.dumps(document, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="darial-policies.json"'},
        )

    return PlainTextResponse(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        media_type="application/x-yaml",
        headers={"Content-Disposition": 'attachment; filename="darial-policies.yaml"'},
    )


@router.post("/observability/policies/custom")
def create_custom_policy(
    payload: CustomPolicyPayload,
    db: Session = Depends(get_db),
):
    ensure_tables(db)
    if payload.operator not in {
        ">", ">=", "<", "<=", "==", "!=", "in", "not_in", "contains"
    }:
        raise HTTPException(status_code=422, detail="Неподдерживаемый оператор")

    policy_id = str(uuid.uuid4())
    config = {
        "field": payload.field,
        "operator": payload.operator,
        "value": payload.value,
        "conditions": payload.conditions,
    }

    db.execute(
        text("""
            INSERT INTO governance_policies (
                id, name, code, description, scope_type, scope_id,
                rule_type, config_json, severity, mode, is_enabled
            )
            VALUES (
                :id, :name, :code, :description, :scope_type, :scope_id,
                'custom_condition', CAST(:config AS JSONB),
                :severity, :mode, TRUE
            )
        """),
        {
            "id": policy_id,
            "name": payload.name,
            "code": payload.code.upper().replace(" ", "_"),
            "description": payload.description,
            "scope_type": payload.scope_type,
            "scope_id": payload.scope_id,
            "config": json.dumps(config),
            "severity": payload.severity,
            "mode": payload.mode,
        },
    )
    create_version(
        db,
        policy_id,
        {
            "name": payload.name,
            "code": payload.code,
            "rule_type": "custom_condition",
            "config": config,
        },
        payload.actor,
        "Создание пользовательской политики",
    )
    write_audit(
        db,
        policy_id,
        "custom_create",
        payload.actor,
        {"field": payload.field, "operator": payload.operator},
    )
    db.commit()
    return {"id": policy_id, "code": payload.code.upper().replace(" ", "_")}


@router.get("/observability/policies/{policy_id}/versions")
def list_versions(policy_id: str, db: Session = Depends(get_db)):
    ensure_tables(db)
    rows = db.execute(
        text("""
            SELECT id, policy_id, version, snapshot_json,
                   changed_by, change_note, created_at
            FROM governance_policy_versions
            WHERE policy_id = :policy_id
            ORDER BY version DESC
        """),
        {"policy_id": policy_id},
    ).mappings().all()
    return [dict(row) for row in rows]


@router.get("/observability/policies/audit")
def policy_audit(db: Session = Depends(get_db)):
    ensure_tables(db)
    rows = db.execute(
        text("""
            SELECT id, policy_id, action, actor, details_json, created_at
            FROM governance_policy_audit
            ORDER BY created_at DESC
            LIMIT 300
        """)
    ).mappings().all()
    return [dict(row) for row in rows]
