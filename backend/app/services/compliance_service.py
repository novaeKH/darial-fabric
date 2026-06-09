from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.base import (
    AuditLog,
    File,
    FileStatus,
    FlowRun,
    Permission,
    SecurityFinding,
)


SECURITY_FINDING_SEVERITIES = ["low", "medium", "high", "critical"]
FLOW_STATUSES = ["running", "completed", "failed"]
PERMISSION_STATUSES = ["active", "revoked"]


def _enum_value(value: object) -> str:
    return getattr(value, "value", str(value))


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat()


def _count(db: Session, model, *filters) -> int:
    query = db.query(model)
    for condition in filters:
        query = query.filter(condition)
    return query.count()


def _count_audit_action(db: Session, action: str) -> int:
    return _count(db, AuditLog, AuditLog.action == action)


def _count_by_column(db: Session, model, column) -> dict[str, int]:
    rows = db.query(column, func.count(model.id)).group_by(column).all()
    return {str(key): int(count) for key, count in rows}


def _count_security_by_severity(db: Session) -> dict[str, int]:
    counts = {severity: 0 for severity in SECURITY_FINDING_SEVERITIES}
    counts.update(_count_by_column(db, SecurityFinding, SecurityFinding.severity))
    return counts


def _count_flows_by_status(db: Session) -> dict[str, int]:
    counts = {status: 0 for status in FLOW_STATUSES}
    counts.update(_count_by_column(db, FlowRun, FlowRun.status))
    return counts


def _count_permissions_by_status(db: Session) -> dict[str, int]:
    counts = {status: 0 for status in PERMISSION_STATUSES}
    counts.update(_count_by_column(db, Permission, Permission.status))
    return counts


def _count_files_by_status(db: Session) -> dict[str, int]:
    raw_counts = db.query(File.status, func.count(File.id)).group_by(File.status).all()
    return {_enum_value(status): int(count) for status, count in raw_counts}


def _count_files_by_classification(db: Session) -> dict[str, int]:
    raw_counts = db.query(File.classification, func.count(File.id)).group_by(File.classification).all()
    return {_enum_value(classification): int(count) for classification, count in raw_counts}


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


def _build_controls() -> dict[str, Any]:
    return {
        "encryption": {
            "enabled": True,
            "algorithm": "AES-256-GCM",
            "per_file_dek": True,
            "dek_wrapping": "local-KEK in MVP; replaceable by Vault/KMS in production",
        },
        "access_control": {
            "enabled": True,
            "policy_engine": True,
            "temporary_permissions": True,
            "file_permissions": True,
            "folder_permissions": True,
        },
        "monitoring": {
            "audit_enabled": True,
            "lineage_enabled": True,
            "policy_simulator_enabled": True,
            "compliance_report_enabled": True,
        },
        "security": {
            "security_scanner_enabled": True,
            "quarantine_enabled": True,
            "quarantine_blocks_decrypt": True,
        },
    }


def generate_compliance_report(db: Session) -> dict:
    total_files = _count(db, File)
    approved_files = _count(db, File, File.status == FileStatus.approved)
    quarantined_files = _count(db, File, File.status == FileStatus.quarantined)
    blocked_files = _count(db, File, File.status == FileStatus.blocked)
    archived_files = _count(db, File, File.status == FileStatus.archived)

    total_security_findings = _count(db, SecurityFinding)
    security_by_severity = _count_security_by_severity(db)
    high_findings = security_by_severity.get("high", 0)
    critical_findings = security_by_severity.get("critical", 0)

    upload_operations = _count_audit_action(db, "upload_file")
    encrypt_operations = _count_audit_action(db, "encrypt_file")
    decrypt_operations = _count_audit_action(db, "decrypt_file")
    read_operations = _count_audit_action(db, "read_file")
    denied_access = _count(db, AuditLog, AuditLog.status == "denied")
    quarantine_events = _count_audit_action(db, "quarantine_file")
    release_events = _count_audit_action(db, "release_from_quarantine")

    flow_runs = _count(db, FlowRun)
    flow_by_status = _count_flows_by_status(db)

    permission_by_status = _count_permissions_by_status(db)
    active_permissions = permission_by_status.get("active", 0)
    revoked_permissions = permission_by_status.get("revoked", 0)

    files_by_status = _count_files_by_status(db)
    files_by_classification = _count_files_by_classification(db)

    encryption_coverage = _safe_ratio(encrypt_operations, upload_operations)
    decrypt_to_read_ratio = _safe_ratio(decrypt_operations, read_operations)
    quarantine_ratio = _safe_ratio(quarantined_files, total_files)
    denied_access_ratio = _safe_ratio(denied_access, max(read_operations + denied_access, 1))

    risk_flags = []
    if critical_findings > 0:
        risk_flags.append("critical_findings_present")
    if high_findings > 0:
        risk_flags.append("high_findings_present")
    if quarantined_files > 0:
        risk_flags.append("quarantined_files_present")
    if denied_access > 0:
        risk_flags.append("denied_access_events_present")
    if upload_operations > encrypt_operations:
        risk_flags.append("some_uploads_without_encrypt_event")

    overall_status = "healthy"
    if critical_findings > 0 or blocked_files > 0:
        overall_status = "attention_required"
    elif quarantined_files > 0 or high_findings > 0 or denied_access > 0:
        overall_status = "controlled_risk"

    return {
        "report_type": "compliance_report",
        "generated_at": _utc_now_iso(),
        "overall_status": overall_status,
        "summary": {
            "total_files": total_files,
            "approved_files": approved_files,
            "quarantined_files": quarantined_files,
            "blocked_files": blocked_files,
            "archived_files": archived_files,
            "security_findings": total_security_findings,
            "high_findings": high_findings,
            "critical_findings": critical_findings,
            "upload_operations": upload_operations,
            "encrypt_operations": encrypt_operations,
            "read_operations": read_operations,
            "decrypt_operations": decrypt_operations,
            "denied_access": denied_access,
            "quarantine_events": quarantine_events,
            "release_from_quarantine_events": release_events,
            "flow_runs": flow_runs,
            "completed_flow_runs": flow_by_status.get("completed", 0),
            "failed_flow_runs": flow_by_status.get("failed", 0),
            "active_permissions": active_permissions,
            "revoked_permissions": revoked_permissions,
        },
        "breakdowns": {
            "files_by_status": files_by_status,
            "files_by_classification": files_by_classification,
            "security_findings_by_severity": security_by_severity,
            "flows_by_status": flow_by_status,
            "permissions_by_status": permission_by_status,
        },
        "metrics": {
            "encryption_coverage": encryption_coverage,
            "decrypt_to_read_ratio": decrypt_to_read_ratio,
            "quarantine_ratio": quarantine_ratio,
            "denied_access_ratio": denied_access_ratio,
        },
        "security_posture": _build_controls(),
        "risk_flags": risk_flags,
        "notes": [
            "All file uploads are expected to be encrypted with AES-256-GCM.",
            "Every successful read operation should trigger a decrypt_file audit event.",
            "High and critical security findings move files to quarantine.",
            "Policy Engine blocks access to quarantined files before decrypt.",
            "Data lineage connects source and derived artifacts.",
            "In MVP, local KEK is used; production can replace it with Vault/KMS.",
        ],
    }