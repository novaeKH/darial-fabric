from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db

router = APIRouter(tags=["RBAC"])


def ensure_tables(db: Session) -> None:
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS rbac_principals (
            id VARCHAR(64) PRIMARY KEY,
            email VARCHAR(255) NOT NULL UNIQUE,
            display_name VARCHAR(255) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'active',
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS rbac_roles (
            id VARCHAR(64) PRIMARY KEY,
            code VARCHAR(64) NOT NULL UNIQUE,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            is_system BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS rbac_permissions (
            id VARCHAR(64) PRIMARY KEY,
            code VARCHAR(128) NOT NULL UNIQUE,
            name VARCHAR(255) NOT NULL,
            description TEXT
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS rbac_role_permissions (
            role_id VARCHAR(64) NOT NULL,
            permission_id VARCHAR(64) NOT NULL,
            PRIMARY KEY (role_id, permission_id)
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS rbac_user_roles (
            id VARCHAR(64) PRIMARY KEY,
            principal_id VARCHAR(64) NOT NULL,
            role_id VARCHAR(64) NOT NULL,
            scope_type VARCHAR(32) NOT NULL DEFAULT 'organization',
            scope_id VARCHAR(64),
            assigned_by VARCHAR(255),
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            UNIQUE(principal_id, role_id, scope_type, scope_id)
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS rbac_audit_log (
            id VARCHAR(64) PRIMARY KEY,
            action VARCHAR(128) NOT NULL,
            actor VARCHAR(255),
            principal_id VARCHAR(64),
            role_id VARCHAR(64),
            details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """))
    db.commit()


def audit(
    db: Session,
    action: str,
    actor: str,
    *,
    principal_id: str | None = None,
    role_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    db.execute(
        text("""
            INSERT INTO rbac_audit_log (
                id, action, actor, principal_id, role_id, details_json
            )
            VALUES (
                :id, :action, :actor, :principal_id, :role_id,
                CAST(:details AS JSONB)
            )
        """),
        {
            "id": str(uuid.uuid4()),
            "action": action,
            "actor": actor,
            "principal_id": principal_id,
            "role_id": role_id,
            "details": json.dumps(details or {}),
        },
    )


class PrincipalCreate(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=2, max_length=255)
    actor: str = "admin@darial.local"


class AssignmentCreate(BaseModel):
    principal_id: str
    role_id: str
    scope_type: str = "organization"
    scope_id: str | None = None
    actor: str = "admin@darial.local"


class StatusUpdate(BaseModel):
    status: str
    actor: str = "admin@darial.local"


@router.get("/rbac/summary")
def rbac_summary(db: Session = Depends(get_db)):
    ensure_tables(db)
    row = db.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM rbac_principals) AS users,
            (SELECT COUNT(*) FROM rbac_principals WHERE status='active') AS active_users,
            (SELECT COUNT(*) FROM rbac_roles) AS roles,
            (SELECT COUNT(*) FROM rbac_user_roles) AS assignments,
            (SELECT COUNT(*) FROM rbac_audit_log) AS audit_events
    """)).mappings().one()
    return dict(row)


@router.get("/rbac/principals")
def list_principals(db: Session = Depends(get_db)):
    ensure_tables(db)
    principals = db.execute(text("""
        SELECT id, email, display_name, status, created_at, updated_at
        FROM rbac_principals
        ORDER BY display_name
    """)).mappings().all()

    result = []
    for principal in principals:
        assignments = db.execute(
            text("""
                SELECT ur.id, ur.scope_type, ur.scope_id, ur.created_at,
                       r.id AS role_id, r.code AS role_code, r.name AS role_name
                FROM rbac_user_roles ur
                JOIN rbac_roles r ON r.id = ur.role_id
                WHERE ur.principal_id = :principal_id
                ORDER BY r.name
            """),
            {"principal_id": principal["id"]},
        ).mappings().all()

        result.append({
            **dict(principal),
            "assignments": [dict(item) for item in assignments],
        })

    return result


@router.post("/rbac/principals")
def create_principal(
    payload: PrincipalCreate,
    db: Session = Depends(get_db),
):
    ensure_tables(db)
    principal_id = str(uuid.uuid4())
    try:
        db.execute(
            text("""
                INSERT INTO rbac_principals (
                    id, email, display_name
                )
                VALUES (:id, :email, :display_name)
            """),
            {
                "id": principal_id,
                "email": payload.email.lower(),
                "display_name": payload.display_name,
            },
        )
        audit(
            db,
            "principal_created",
            payload.actor,
            principal_id=principal_id,
            details={"email": payload.email.lower()},
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Пользователь с таким email уже существует",
        ) from exc

    return {
        "id": principal_id,
        "email": payload.email.lower(),
        "display_name": payload.display_name,
        "status": "active",
    }


@router.patch("/rbac/principals/{principal_id}/status")
def update_principal_status(
    principal_id: str,
    payload: StatusUpdate,
    db: Session = Depends(get_db),
):
    ensure_tables(db)
    if payload.status not in {"active", "disabled"}:
        raise HTTPException(status_code=422, detail="Unsupported status")

    result = db.execute(
        text("""
            UPDATE rbac_principals
            SET status=:status, updated_at=NOW()
            WHERE id=:id
            RETURNING id
        """),
        {"id": principal_id, "status": payload.status},
    ).first()

    if not result:
        raise HTTPException(status_code=404, detail="Principal not found")

    audit(
        db,
        "principal_status_changed",
        payload.actor,
        principal_id=principal_id,
        details={"status": payload.status},
    )
    db.commit()
    return {"id": principal_id, "status": payload.status}


@router.get("/rbac/roles")
def list_roles(db: Session = Depends(get_db)):
    ensure_tables(db)
    roles = db.execute(text("""
        SELECT id, code, name, description, is_system, created_at
        FROM rbac_roles
        ORDER BY name
    """)).mappings().all()

    result = []
    for role in roles:
        permissions = db.execute(
            text("""
                SELECT p.code, p.name
                FROM rbac_role_permissions rp
                JOIN rbac_permissions p ON p.id = rp.permission_id
                WHERE rp.role_id = :role_id
                ORDER BY p.code
            """),
            {"role_id": role["id"]},
        ).mappings().all()

        result.append({
            **dict(role),
            "permissions": [dict(item) for item in permissions],
        })

    return result


@router.post("/rbac/assignments")
def create_assignment(
    payload: AssignmentCreate,
    db: Session = Depends(get_db),
):
    ensure_tables(db)

    if payload.scope_type not in {"organization", "product"}:
        raise HTTPException(status_code=422, detail="Unsupported scope_type")
    if payload.scope_type == "product" and not payload.scope_id:
        raise HTTPException(
            status_code=422,
            detail="scope_id is required for product scope",
        )

    assignment_id = str(uuid.uuid4())

    try:
        db.execute(
            text("""
                INSERT INTO rbac_user_roles (
                    id, principal_id, role_id, scope_type, scope_id, assigned_by
                )
                VALUES (
                    :id, :principal_id, :role_id, :scope_type,
                    :scope_id, :assigned_by
                )
            """),
            {
                "id": assignment_id,
                "principal_id": payload.principal_id,
                "role_id": payload.role_id,
                "scope_type": payload.scope_type,
                "scope_id": payload.scope_id,
                "assigned_by": payload.actor,
            },
        )
        audit(
            db,
            "role_assigned",
            payload.actor,
            principal_id=payload.principal_id,
            role_id=payload.role_id,
            details={
                "scope_type": payload.scope_type,
                "scope_id": payload.scope_id,
            },
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Такое назначение уже существует",
        ) from exc

    return {
        "id": assignment_id,
        **payload.model_dump(),
    }


@router.delete("/rbac/assignments/{assignment_id}")
def delete_assignment(
    assignment_id: str,
    actor: str = "admin@darial.local",
    db: Session = Depends(get_db),
):
    ensure_tables(db)
    current = db.execute(
        text("""
            SELECT principal_id, role_id, scope_type, scope_id
            FROM rbac_user_roles
            WHERE id=:id
        """),
        {"id": assignment_id},
    ).mappings().first()

    if not current:
        raise HTTPException(status_code=404, detail="Assignment not found")

    db.execute(
        text("DELETE FROM rbac_user_roles WHERE id=:id"),
        {"id": assignment_id},
    )
    audit(
        db,
        "role_removed",
        actor,
        principal_id=current["principal_id"],
        role_id=current["role_id"],
        details={
            "scope_type": current["scope_type"],
            "scope_id": current["scope_id"],
        },
    )
    db.commit()
    return {"id": assignment_id, "deleted": True}


@router.get("/rbac/audit")
def list_audit(db: Session = Depends(get_db)):
    ensure_tables(db)
    rows = db.execute(text("""
        SELECT a.id, a.action, a.actor, a.principal_id, a.role_id,
               a.details_json, a.created_at,
               p.email AS principal_email,
               p.display_name AS principal_name,
               r.code AS role_code,
               r.name AS role_name
        FROM rbac_audit_log a
        LEFT JOIN rbac_principals p ON p.id = a.principal_id
        LEFT JOIN rbac_roles r ON r.id = a.role_id
        ORDER BY a.created_at DESC
        LIMIT 300
    """)).mappings().all()
    return [dict(row) for row in rows]


@router.get("/rbac/check")
def check_permission(
    principal_id: str,
    permission: str,
    product_id: str | None = None,
    db: Session = Depends(get_db),
):
    ensure_tables(db)

    principal = db.execute(
        text("""
            SELECT id, status
            FROM rbac_principals
            WHERE id=:id
        """),
        {"id": principal_id},
    ).mappings().first()

    if not principal or principal["status"] != "active":
        return {"allowed": False, "reason": "principal_inactive"}

    rows = db.execute(
        text("""
            SELECT ur.scope_type, ur.scope_id, p.code AS permission_code
            FROM rbac_user_roles ur
            JOIN rbac_role_permissions rp ON rp.role_id = ur.role_id
            JOIN rbac_permissions p ON p.id = rp.permission_id
            WHERE ur.principal_id=:principal_id
              AND p.code=:permission
        """),
        {
            "principal_id": principal_id,
            "permission": permission,
        },
    ).mappings().all()

    for row in rows:
        if row["scope_type"] == "organization":
            return {"allowed": True, "scope": "organization"}
        if (
            row["scope_type"] == "product"
            and product_id
            and row["scope_id"] == product_id
        ):
            return {"allowed": True, "scope": "product"}

    return {"allowed": False, "reason": "permission_not_granted"}
