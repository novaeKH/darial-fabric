from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.base import (
    Agent,
    AuditSeverity,
    File,
    Folder,
    Permission,
    PermissionAction,
    ResourceType,
    SubjectType,
)
from app.services.audit_service import log_event


ACTIVE_STATUS = "active"
REVOKED_STATUS = "revoked"


def _enum_value(value: object) -> str:
    return getattr(value, "value", str(value))


def _now_utc() -> datetime:
    return datetime.utcnow()


def _parse_resource_type(resource_type: str) -> ResourceType:
    try:
        return ResourceType(resource_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid resource_type") from exc


def _parse_action(action: str) -> PermissionAction:
    try:
        return PermissionAction(action)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid action") from exc


def _get_agent_or_404(db: Session, agent_id: str, label: str = "Agent") -> Agent:
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail=f"{label} not found")

    return agent


def _validate_subject_agent(db: Session, agent_id: str) -> Agent:
    agent = _get_agent_or_404(db, agent_id, "Subject agent")

    if agent.status != ACTIVE_STATUS:
        raise HTTPException(status_code=403, detail="Subject agent is not active")

    return agent


def _validate_actor_agent(db: Session, agent_id: str | None) -> Agent | None:
    if not agent_id:
        return None

    agent = _get_agent_or_404(db, agent_id, "Actor agent")

    if agent.status != ACTIVE_STATUS:
        raise HTTPException(status_code=403, detail="Actor agent is not active")

    return agent


def _get_resource_or_404(
    db: Session,
    resource_type: ResourceType,
    resource_id: str,
) -> File | Folder:
    if resource_type == ResourceType.file:
        resource = db.query(File).filter(File.id == resource_id).first()
    elif resource_type == ResourceType.folder:
        resource = db.query(Folder).filter(Folder.id == resource_id).first()
    else:
        raise HTTPException(
            status_code=400,
            detail="Only file and folder permissions are supported in MVP",
        )

    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")

    return resource


def _calculate_expires_at(expires_in_minutes: int | None) -> datetime | None:
    if expires_in_minutes is None:
        return None

    if expires_in_minutes <= 0:
        raise HTTPException(status_code=400, detail="expires_in_minutes must be greater than zero")

    return _now_utc() + timedelta(minutes=expires_in_minutes)


def _find_existing_active_permission(
    db: Session,
    subject_agent_id: str,
    resource_type: ResourceType,
    resource_id: str,
    action: PermissionAction,
) -> Permission | None:
    return (
        db.query(Permission)
        .filter(
            Permission.subject_type == SubjectType.agent,
            Permission.subject_id == subject_agent_id,
            Permission.resource_type == resource_type,
            Permission.resource_id == resource_id,
            Permission.action == action,
            Permission.status == ACTIVE_STATUS,
            or_(Permission.expires_at.is_(None), Permission.expires_at >= _now_utc()),
        )
        .first()
    )


def _log_permission_event(
    db: Session,
    actor_agent_id: str | None,
    action: str,
    permission: Permission,
    severity: AuditSeverity,
    reason: str | None = None,
    extra_details: dict | None = None,
) -> None:
    log_event(
        db=db,
        actor_agent_id=actor_agent_id,
        action=action,
        resource_type=_enum_value(permission.resource_type),
        resource_id=permission.resource_id,
        severity=severity,
        reason=reason,
        details={
            "permission_id": permission.id,
            "subject_type": _enum_value(permission.subject_type),
            "subject_id": permission.subject_id,
            "permission_action": _enum_value(permission.action),
            "permission_status": permission.status,
            "expires_at": permission.expires_at.isoformat() if permission.expires_at else None,
            **(extra_details or {}),
        },
    )


def grant_permission(
    db: Session,
    subject_agent_id: str,
    resource_type: str,
    resource_id: str,
    action: str,
    expires_in_minutes: int | None = None,
    reason: str | None = None,
    granted_by_agent_id: str | None = None,
) -> Permission:
    _validate_subject_agent(db, subject_agent_id)
    _validate_actor_agent(db, granted_by_agent_id)

    resource_type_enum = _parse_resource_type(resource_type)
    action_enum = _parse_action(action)
    _get_resource_or_404(db, resource_type_enum, resource_id)

    expires_at = _calculate_expires_at(expires_in_minutes)

    existing_permission = _find_existing_active_permission(
        db=db,
        subject_agent_id=subject_agent_id,
        resource_type=resource_type_enum,
        resource_id=resource_id,
        action=action_enum,
    )

    if existing_permission:
        old_expires_at = existing_permission.expires_at
        existing_permission.expires_at = expires_at
        existing_permission.reason = reason or existing_permission.reason

        db.add(existing_permission)
        db.commit()
        db.refresh(existing_permission)

        _log_permission_event(
            db=db,
            actor_agent_id=granted_by_agent_id,
            action="extend_access",
            permission=existing_permission,
            severity=AuditSeverity.info,
            reason=reason,
            extra_details={
                "old_expires_at": old_expires_at.isoformat() if old_expires_at else None,
                "updated_existing_permission": True,
            },
        )

        return existing_permission

    permission = Permission(
        subject_type=SubjectType.agent,
        subject_id=subject_agent_id,
        resource_type=resource_type_enum,
        resource_id=resource_id,
        action=action_enum,
        expires_at=expires_at,
        status=ACTIVE_STATUS,
        reason=reason,
    )

    db.add(permission)
    db.commit()
    db.refresh(permission)

    _log_permission_event(
        db=db,
        actor_agent_id=granted_by_agent_id,
        action="grant_access",
        permission=permission,
        severity=AuditSeverity.info,
        reason=reason,
        extra_details={
            "created_new_permission": True,
        },
    )

    return permission


def revoke_permission(
    db: Session,
    permission_id: str,
    revoked_by_agent_id: str | None = None,
) -> Permission:
    _validate_actor_agent(db, revoked_by_agent_id)

    permission = db.query(Permission).filter(Permission.id == permission_id).first()
    if not permission:
        raise HTTPException(status_code=404, detail="Permission not found")

    if permission.status == REVOKED_STATUS:
        _log_permission_event(
            db=db,
            actor_agent_id=revoked_by_agent_id,
            action="revoke_access_skipped",
            permission=permission,
            severity=AuditSeverity.info,
            reason="permission_already_revoked",
        )
        return permission

    old_status = permission.status
    permission.status = REVOKED_STATUS

    db.add(permission)
    db.commit()
    db.refresh(permission)

    _log_permission_event(
        db=db,
        actor_agent_id=revoked_by_agent_id,
        action="revoke_access",
        permission=permission,
        severity=AuditSeverity.warning,
        reason="permission_revoked",
        extra_details={
            "old_status": old_status,
        },
    )

    return permission