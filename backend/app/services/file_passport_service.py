from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.base import (
    Agent,
    AuditLog,
    AuditSeverity,
    File,
    FileLineage,
    Folder,
    Permission,
    ResourceType,
    SecurityFinding,
    SubjectType,
    Workspace,
)


RECENT_AUDIT_LIMIT = 20


def _enum_value(value: object) -> str:
    return getattr(value, "value", str(value))


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _file_metadata(file: File | None) -> dict[str, Any]:
    if not file:
        return {}


    return file.metadata_json or {}


def _display_name_for_file(file: File | None) -> str | None:
    if not file:
        return None

    metadata = _file_metadata(file)
    if metadata.get("display_name"):
        return str(metadata["display_name"])

    name = file.name or ""
    if "qa_report" in name:
        return "QA-отчёт"
    if "summary_" in name:
        return "Краткая сводка"
    if "research_" in name:
        return "Исследовательская сводка"
    if "processed_" in name:
        return "Обработанный датасет"
    if "risky_security_events" in name or "security_events" in name:
        return "События безопасности"
    if "clean_server_metrics" in name or "server_metrics" in name:
        return "Метрики серверов"
    if "business_events" in name:
        return "Бизнес-события"

    return name


def _display_type_for_file(file: File | None) -> str | None:
    if not file:
        return None

    metadata = _file_metadata(file)
    if metadata.get("display_type"):
        return str(metadata["display_type"])

    name = file.name or ""
    if "qa_report" in name:
        return "QA-отчёт"
    if "summary_" in name:
        return "Автоматическая сводка"
    if "research_" in name:
        return "Исследовательская сводка"
    if "processed_" in name:
        return "Обработанный датасет"
    if "security_events" in name:
        return "Датасет безопасности"
    if "server_metrics" in name:
        return "Датасет метрик"
    if "business_events" in name:
        return "Бизнес-датасет"

    return "Файл"


def _description_for_file(file: File | None) -> str | None:
    metadata = _file_metadata(file)
    description = metadata.get("description")
    return str(description) if description else None


def _agent_name_by_id(db: Session, agent_ids: set[str | None]) -> dict[str, str]:
    clean_ids = {agent_id for agent_id in agent_ids if agent_id}
    if not clean_ids:
        return {}

    agents = db.query(Agent).filter(Agent.id.in_(clean_ids)).all()
    return {agent.id: agent.name for agent in agents}


def _file_summary_by_id(db: Session, file_ids: set[str | None]) -> dict[str, dict[str, Any]]:
    clean_ids = {file_id for file_id in file_ids if file_id}
    if not clean_ids:
        return {}

    files = db.query(File).filter(File.id.in_(clean_ids)).all()
    return {
        file.id: {
            "id": file.id,
            "name": file.name,
            "display_name": _display_name_for_file(file),
            "display_type": _display_type_for_file(file),
            "status": _enum_value(file.status),
            "classification": _enum_value(file.classification),
        }
        for file in files
    }


def _folder_chain(db: Session, folder: Folder | None) -> list[dict[str, Any]]:
    if not folder:
        return []

    chain: list[dict[str, Any]] = []
    visited: set[str] = set()
    current = folder

    while current and current.id not in visited:
        visited.add(current.id)
        chain.append(
            {
                "id": current.id,
                "name": current.name,
                "label": current.name,
                "parent_folder_id": current.parent_folder_id,
                "created_at": _iso(current.created_at),
            }
        )

        if not current.parent_folder_id:
            break

        current = db.query(Folder).filter(Folder.id == current.parent_folder_id).first()

    return chain


def _serialize_permission(
    permission: Permission,
    subject_name_by_id: dict[str, str],
) -> dict[str, Any]:
    subject_type = _enum_value(permission.subject_type)
    subject_name = None

    if subject_type == SubjectType.agent.value:
        subject_name = subject_name_by_id.get(permission.subject_id)

    return {
        "id": permission.id,
        "subject_type": subject_type,
        "subject_id": permission.subject_id,
        "subject_name": subject_name,
        "resource_type": _enum_value(permission.resource_type),
        "resource_id": permission.resource_id,
        "action": _enum_value(permission.action),
        "status": permission.status,
        "expires_at": _iso(permission.expires_at),
        "reason": permission.reason,
        "created_at": _iso(permission.created_at),
    }


def _serialize_finding(finding: SecurityFinding) -> dict[str, Any]:
    return {
        "id": finding.id,
        "finding_type": finding.finding_type,
        "severity": finding.severity,
        "description": finding.description,
        "created_at": _iso(finding.created_at),
    }


def _serialize_audit_event(
    event: AuditLog,
    actor_name_by_id: dict[str, str],
) -> dict[str, Any]:
    return {
        "id": event.id,
        "actor_user_id": event.actor_user_id,
        "actor_agent_id": event.actor_agent_id,
        "actor_agent_name": actor_name_by_id.get(event.actor_agent_id),
        "action": event.action,
        "resource_type": event.resource_type,
        "resource_id": event.resource_id,
        "status": event.status,
        "severity": _enum_value(event.severity),
        "reason": event.reason,
        "details": event.details,
        "created_at": _iso(event.created_at),
    }


def _serialize_lineage_item(
    item: FileLineage,
    related_file_id: str,
    file_summary_by_id: dict[str, dict[str, Any]],
    agent_name_by_id: dict[str, str],
) -> dict[str, Any]:
    related_file = file_summary_by_id.get(related_file_id, {})
    return {
        "lineage_id": item.id,
        "file_id": related_file_id,
        "file_name": related_file.get("name"),
        "display_name": related_file.get("display_name"),
        "display_type": related_file.get("display_type"),
        "file_status": related_file.get("status"),
        "file_classification": related_file.get("classification"),
        "flow_run_id": item.flow_run_id,
        "created_by_agent_id": item.created_by_agent_id,
        "created_by_agent": agent_name_by_id.get(item.created_by_agent_id),
        "created_at": _iso(item.created_at),
    }


def _permission_summary(permissions: list[Permission]) -> dict[str, int]:
    active_count = sum(1 for permission in permissions if permission.status == "active")
    revoked_count = sum(1 for permission in permissions if permission.status == "revoked")
    expiring_count = sum(
        1
        for permission in permissions
        if permission.status == "active" and permission.expires_at is not None
    )

    return {
        "total": len(permissions),
        "active": active_count,
        "revoked": revoked_count,
        "active_with_expiration": expiring_count,
    }


def _security_summary(findings: list[SecurityFinding]) -> dict[str, Any]:
    by_severity: dict[str, int] = {}
    for finding in findings:
        by_severity[finding.severity] = by_severity.get(finding.severity, 0) + 1

    return {
        "total": len(findings),
        "by_severity": by_severity,
        "has_high_or_critical": any(
            finding.severity in {"high", "critical"} for finding in findings
        ),
    }


def _audit_summary_counts(audit_events: list[AuditLog]) -> dict[str, Any]:
    by_action: dict[str, int] = {}
    by_severity: dict[str, int] = {}

    for event in audit_events:
        by_action[event.action] = by_action.get(event.action, 0) + 1
        severity = _enum_value(event.severity)
        by_severity[severity] = by_severity.get(severity, 0) + 1

    return {
        "recent_count": len(audit_events),
        "by_action": by_action,
        "by_severity": by_severity,
    }


def _human_file_summary(file: File, owner_agent: Agent | None, folder: Folder | None) -> dict[str, Any]:
    return {
        "title": _display_name_for_file(file),
        "type": _display_type_for_file(file),
        "description": _description_for_file(file),
        "status": _enum_value(file.status),
        "classification": _enum_value(file.classification),
        "owner": owner_agent.name if owner_agent else None,
        "folder": folder.name if folder else None,
        "size": file.size,
        "created_at": _iso(file.created_at),
    }


def get_file_passport(db: Session, file_id: str) -> dict:
    file = db.query(File).filter(File.id == file_id).first()

    if not file:
        return {
            "status": "error",
            "message": "file_not_found",
        }

    owner_agent = db.query(Agent).filter(Agent.id == file.owner_agent_id).first()
    workspace = db.query(Workspace).filter(Workspace.id == file.workspace_id).first()
    folder = db.query(Folder).filter(Folder.id == file.folder_id).first()

    permissions = (
        db.query(Permission)
        .filter(
            Permission.resource_type == ResourceType.file,
            Permission.resource_id == file.id,
        )
        .order_by(Permission.created_at.desc())
        .all()
    )

    folder_permissions = []
    if folder:
        folder_ids = [item["id"] for item in _folder_chain(db, folder)]
        folder_permissions = (
            db.query(Permission)
            .filter(
                Permission.resource_type == ResourceType.folder,
                Permission.resource_id.in_(folder_ids),
            )
            .order_by(Permission.created_at.desc())
            .all()
        )

    security_findings = (
        db.query(SecurityFinding)
        .filter(SecurityFinding.file_id == file.id)
        .order_by(SecurityFinding.created_at.desc())
        .all()
    )

    audit_events = (
        db.query(AuditLog)
        .filter(AuditLog.resource_type == "file", AuditLog.resource_id == file.id)
        .order_by(AuditLog.created_at.desc())
        .limit(RECENT_AUDIT_LIMIT)
        .all()
    )

    parents = db.query(FileLineage).filter(FileLineage.derived_file_id == file.id).all()
    children = db.query(FileLineage).filter(FileLineage.source_file_id == file.id).all()

    related_file_ids = {item.source_file_id for item in parents} | {item.derived_file_id for item in children}
    related_agent_ids = {item.created_by_agent_id for item in parents + children}
    permission_agent_ids = {
        permission.subject_id
        for permission in permissions + folder_permissions
        if _enum_value(permission.subject_type) == SubjectType.agent.value
    }
    audit_actor_agent_ids = {event.actor_agent_id for event in audit_events}

    file_summaries = _file_summary_by_id(db, related_file_ids)
    agent_names = _agent_name_by_id(
        db,
        related_agent_ids | permission_agent_ids | audit_actor_agent_ids | {file.owner_agent_id},
    )

    file_permissions = [
        _serialize_permission(permission, agent_names)
        for permission in permissions
    ]
    inherited_folder_permissions = [
        _serialize_permission(permission, agent_names)
        for permission in folder_permissions
    ]

    findings = [_serialize_finding(finding) for finding in security_findings]
    recent_audit_events = [
        _serialize_audit_event(event, agent_names)
        for event in audit_events
    ]

    parent_files = [
        _serialize_lineage_item(
            item=item,
            related_file_id=item.source_file_id,
            file_summary_by_id=file_summaries,
            agent_name_by_id=agent_names,
        )
        for item in parents
    ]

    child_files = [
        _serialize_lineage_item(
            item=item,
            related_file_id=item.derived_file_id,
            file_summary_by_id=file_summaries,
            agent_name_by_id=agent_names,
        )
        for item in children
    ]

    file_metadata = file.metadata_json or {}

    return {
        "status": "ok",
        "file": {
            "id": file.id,
            "name": file.name,
            "display_name": _display_name_for_file(file),
            "display_type": _display_type_for_file(file),
            "description": _description_for_file(file),
            "original_filename": file_metadata.get("original_filename", file.name),
            "classification": _enum_value(file.classification),
            "status": _enum_value(file.status),
            "size": file.size,
            "content_hash": file.content_hash,
            "created_by_flow_id": file.created_by_flow_id,
            "created_at": _iso(file.created_at),
            "metadata": file_metadata,
        },
        "human_summary": _human_file_summary(file, owner_agent, folder),
        "location": {
            "workspace_id": workspace.id if workspace else None,
            "workspace_name": workspace.name if workspace else None,
            "folder_id": folder.id if folder else None,
            "folder_name": folder.name if folder else None,
            "folder_path": " / ".join(reversed([item["name"] for item in _folder_chain(db, folder)])),
            "folder_chain": _folder_chain(db, folder),
            "object_key": file.object_key,
        },
        "owner": {
            "agent_id": owner_agent.id if owner_agent else None,
            "agent_name": owner_agent.name if owner_agent else None,
            "label": owner_agent.name if owner_agent else None,
            "agent_role": owner_agent.role if owner_agent else None,
            "agent_status": owner_agent.status if owner_agent else None,
            "agent_clearance_level": _enum_value(owner_agent.clearance_level) if owner_agent else None,
        },
        "encryption": {
            "enabled": True,
            "algorithm": file_metadata.get("encryption", "AES-256-GCM"),
            "dek_per_file": True,
            "dek_wrapping": file_metadata.get("dek_wrapping", "local-KEK"),
            "encrypted_dek_stored": file.encrypted_dek is not None,
            "nonce_stored": file.nonce is not None,
            "dek_nonce_stored": bool(file_metadata.get("dek_nonce")),
            "content_hash_stored": file.content_hash is not None,
            "summary": "Файл хранится в зашифрованном виде; расшифровка выполняется только после проверки политики доступа.",
        },
        "permissions": file_permissions,
        "inherited_folder_permissions": inherited_folder_permissions,
        "permission_summary": _permission_summary(permissions + folder_permissions),
        "security_findings": findings,
        "security_summary": _security_summary(security_findings),
        "lineage": {
            "parents": parent_files,
            "children": child_files,
            "parents_count": len(parent_files),
            "children_count": len(child_files),
            "summary": "Показывает, из каких файлов был создан текущий файл и какие файлы были получены на его основе.",
        },
        "audit_summary": recent_audit_events,
        "audit_summary_counts": _audit_summary_counts(audit_events),
    }