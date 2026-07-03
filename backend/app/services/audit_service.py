from sqlalchemy.orm import Session

from app.models.base import AuditLog, AuditSeverity


def log_event(
    db: Session,
    action: str,
    status: str = "success",
    severity: AuditSeverity = AuditSeverity.info,
    actor_user_id: str | None = None,
    actor_agent_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    reason: str | None = None,
    details: dict | None = None,
) -> AuditLog:
    event = AuditLog(
        actor_user_id=actor_user_id,
        actor_agent_id=actor_agent_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        status=status,
        severity=severity,
        reason=reason,
        details=details,
    )

    db.add(event)
    db.commit()
    db.refresh(event)
    return event