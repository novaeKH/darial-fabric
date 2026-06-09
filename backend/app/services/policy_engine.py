from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.base import (
    Agent,
    File,
    FileStatus,
    Folder,
    Permission,
    PermissionAction,
    ResourceType,
    SubjectType,
)


CLASSIFICATION_ORDER = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "restricted": 3,
}

BLOCKING_FILE_STATUSES = {
    FileStatus.quarantined,
    FileStatus.blocked,
    FileStatus.deleted,
}


class PolicyDecision:
    ALLOW = "allow"
    DENY = "deny"


def _enum_value(value: object) -> str:
    """Return enum value safely even if SQLAlchemy gives us a raw string."""
    return getattr(value, "value", str(value))


def _now_utc() -> datetime:
    return datetime.utcnow()


def _is_expired(permission: Permission) -> bool:
    if permission.expires_at is None:
        return False

    return permission.expires_at < _now_utc()


def _clearance_allows(agent: Agent, file: File) -> bool:
    agent_level = CLASSIFICATION_ORDER.get(_enum_value(agent.clearance_level), 0)
    file_level = CLASSIFICATION_ORDER.get(_enum_value(file.classification), 0)

    return agent_level >= file_level


def _active_permission_query(
    db: Session,
    agent_id: str,
    resource_type: ResourceType,
    resource_ids: list[str],
    action: PermissionAction,
):
    return db.query(Permission).filter(
        Permission.subject_type == SubjectType.agent,
        Permission.subject_id == agent_id,
        Permission.resource_type == resource_type,
        Permission.resource_id.in_(resource_ids),
        Permission.action == action,
        Permission.status == "active",
        or_(Permission.expires_at.is_(None), Permission.expires_at >= _now_utc()),
    )


def _has_direct_file_permission(
    db: Session,
    agent_id: str,
    file_id: str,
    action: PermissionAction,
) -> bool:
    return (
        _active_permission_query(
            db=db,
            agent_id=agent_id,
            resource_type=ResourceType.file,
            resource_ids=[file_id],
            action=action,
        ).first()
        is not None
    )


def _get_folder_chain_ids(db: Session, folder_id: str | None) -> list[str]:
    """
    Return current folder id and its parents.

    This makes folder permissions work not only on the exact folder, but also
    on parent folders. A permission on /datasets should allow files inside
    /datasets/incoming, unless another policy blocks the file.
    """
    if not folder_id:
        return []

    folder_ids: list[str] = []
    visited: set[str] = set()
    current_folder_id = folder_id

    while current_folder_id and current_folder_id not in visited:
        visited.add(current_folder_id)
        folder_ids.append(current_folder_id)

        folder = db.query(Folder).filter(Folder.id == current_folder_id).first()
        if not folder:
            break

        current_folder_id = folder.parent_folder_id

    return folder_ids


def _has_folder_permission(
    db: Session,
    agent_id: str,
    folder_ids: list[str],
    action: PermissionAction,
) -> bool:
    if not folder_ids:
        return False

    return (
        _active_permission_query(
            db=db,
            agent_id=agent_id,
            resource_type=ResourceType.folder,
            resource_ids=folder_ids,
            action=action,
        ).first()
        is not None
    )


def evaluate_file_access(
    db: Session,
    agent: Agent,
    file: File,
    action: PermissionAction,
) -> dict:
    reasons: list[str] = []

    agent_status = getattr(agent, "status", None)
    file_status = file.status

    if agent_status != "active":
        reasons.append("agent_is_not_active")

    if file_status in BLOCKING_FILE_STATUSES:
        reasons.append(f"file_status_is_{_enum_value(file_status)}")

    if not _clearance_allows(agent, file):
        reasons.append("classification_above_agent_clearance")

    is_owner = file.owner_agent_id == agent.id
    checked_folder_ids = _get_folder_chain_ids(db, file.folder_id)

    has_file_permission = _has_direct_file_permission(
        db=db,
        agent_id=agent.id,
        file_id=file.id,
        action=action,
    )

    has_folder_permission = _has_folder_permission(
        db=db,
        agent_id=agent.id,
        folder_ids=checked_folder_ids,
        action=action,
    )

    # The owner can access its own file only while stronger safety policies pass.
    # Quarantine, blocked/deleted status and insufficient clearance still deny.
    if not is_owner and not has_file_permission and not has_folder_permission:
        reasons.append("agent_has_no_active_permission")

    decision = PolicyDecision.DENY if reasons else PolicyDecision.ALLOW

    return {
        "decision": decision,
        "reasons": reasons,
        "is_owner": is_owner,
        "has_file_permission": has_file_permission,
        "has_folder_permission": has_folder_permission,
        "checked_folder_ids": checked_folder_ids,
    }


def simulate_file_access(
    db: Session,
    agent_id: str,
    file_id: str,
    action: str,
) -> dict:
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        return {
            "decision": PolicyDecision.DENY,
            "reasons": ["agent_not_found"],
        }

    file = db.query(File).filter(File.id == file_id).first()
    if not file:
        return {
            "decision": PolicyDecision.DENY,
            "reasons": ["file_not_found"],
        }

    try:
        action_enum = PermissionAction(action)
    except ValueError:
        return {
            "decision": PolicyDecision.DENY,
            "reasons": ["invalid_action"],
        }

    result = evaluate_file_access(
        db=db,
        agent=agent,
        file=file,
        action=action_enum,
    )

    result["agent"] = {
        "id": agent.id,
        "name": agent.name,
        "clearance_level": _enum_value(agent.clearance_level),
        "risk_level": _enum_value(agent.risk_level),
        "autonomy_level": agent.autonomy_level,
        "status": agent.status,
    }

    result["file"] = {
        "id": file.id,
        "name": file.name,
        "classification": _enum_value(file.classification),
        "status": _enum_value(file.status),
        "owner_agent_id": file.owner_agent_id,
        "folder_id": file.folder_id,
    }

    result["action"] = _enum_value(action_enum)

    return result