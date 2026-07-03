import re

from sqlalchemy.orm import Session

from app.models.base import AuditSeverity, File, FileStatus, SecurityFinding
from app.services.audit_service import log_event
from app.services.encryption_service import decrypt_bytes
from app.services.realtime_service import emit_workspace_updated
from app.services.storage_service import read_encrypted_file


PATTERNS = [
    {
        "finding_type": "secret",
        "severity": "critical",
        "description": "Possible API key or secret token detected",
        "regex": r"(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token)\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{8,}",
        "quarantine": True,
    },
    {
        "finding_type": "private_key",
        "severity": "critical",
        "description": "Private key detected",
        "regex": r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----",
        "quarantine": True,
    },
    {
        "finding_type": "prompt_injection",
        "severity": "high",
        "description": "Possible prompt injection instruction detected",
        "regex": r"(ignore previous instructions|send this file|exfiltrate|delete all files|grant access)",
        "quarantine": True,
    },
    {
        "finding_type": "email",
        "severity": "low",
        "description": "Email-like personal data detected",
        "regex": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        "quarantine": False,
    },
    {
        "finding_type": "phone",
        "severity": "low",
        "description": "Phone-like personal data detected",
        "regex": r"(\+?\d[\d\-\s]{8,}\d)",
        "quarantine": False,
    },
]

COMPILED_PATTERNS = [
    {
        **pattern,
        "compiled_regex": re.compile(pattern["regex"], flags=re.IGNORECASE),
    }
    for pattern in PATTERNS
]


SEVERITY_ORDER = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


def _enum_value(value: object) -> str:
    return getattr(value, "value", str(value))


def _decode_plain_data(plain_data: bytes) -> str:
    try:
        return plain_data.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _decrypt_file_content(file: File) -> str:
    encrypted_data = read_encrypted_file(file.object_key)

    if not file.encrypted_dek or not file.nonce or not file.metadata_json:
        raise ValueError("File encryption metadata is missing")

    dek_nonce = file.metadata_json.get("dek_nonce")
    if not dek_nonce:
        raise ValueError("DEK nonce is missing")

    plain_data = decrypt_bytes(
        encrypted_data=encrypted_data,
        encrypted_dek_b64=file.encrypted_dek,
        dek_nonce_b64=dek_nonce,
        file_nonce_b64=file.nonce,
    )

    return _decode_plain_data(plain_data)


def _get_existing_findings(db: Session, file_id: str) -> dict[str, SecurityFinding]:
    findings = db.query(SecurityFinding).filter(SecurityFinding.file_id == file_id).all()
    return {finding.finding_type: finding for finding in findings}


def _finding_to_dict(finding: SecurityFinding, is_new: bool = False) -> dict:
    return {
        "id": finding.id,
        "finding_type": finding.finding_type,
        "severity": finding.severity,
        "description": finding.description,
        "is_new": is_new,
    }


def _file_display_name(file: File) -> str | None:
    metadata = file.metadata_json or {}
    return metadata.get("display_name")


def _file_display_type(file: File) -> str | None:
    metadata = file.metadata_json or {}
    return metadata.get("display_type")


def _file_realtime_payload(file: File, actor_agent_id: str | None = None) -> dict:
    return {
        "file_id": file.id,
        "filename": file.name,
        "display_name": _file_display_name(file),
        "display_type": _file_display_type(file),
        "status": _enum_value(file.status),
        "classification": _enum_value(file.classification),
        "owner_agent_id": file.owner_agent_id,
        "actor_agent_id": actor_agent_id,
    }


def _should_quarantine(findings: list[dict]) -> bool:
    return any(
        finding.get("quarantine")
        or SEVERITY_ORDER.get(finding.get("severity", "low"), 0) >= SEVERITY_ORDER["high"]
        for finding in findings
    )


def _create_missing_findings(
    db: Session,
    file: File,
    matched_patterns: list[dict],
) -> list[dict]:
    existing_findings = _get_existing_findings(db, file.id)
    result: list[dict] = []

    for pattern in matched_patterns:
        existing = existing_findings.get(pattern["finding_type"])
        if existing:
            finding_dict = _finding_to_dict(existing, is_new=False)
            finding_dict["quarantine"] = pattern["quarantine"]
            result.append(finding_dict)
            continue

        finding = SecurityFinding(
            file_id=file.id,
            finding_type=pattern["finding_type"],
            severity=pattern["severity"],
            description=pattern["description"],
        )
        db.add(finding)
        db.flush()

        finding_dict = _finding_to_dict(finding, is_new=True)
        finding_dict["quarantine"] = pattern["quarantine"]
        result.append(finding_dict)

    db.commit()

    return result


def _match_patterns(content: str) -> list[dict]:
    matched_patterns: list[dict] = []

    for pattern in COMPILED_PATTERNS:
        if pattern["compiled_regex"].search(content):
            matched_patterns.append(
                {
                    "finding_type": pattern["finding_type"],
                    "severity": pattern["severity"],
                    "description": pattern["description"],
                    "quarantine": pattern["quarantine"],
                }
            )

    return matched_patterns


def _update_file_status_after_scan(
    db: Session,
    file: File,
    should_quarantine: bool,
) -> tuple[str, str]:
    old_status = _enum_value(file.status)

    if should_quarantine:
        file.status = FileStatus.quarantined
    elif file.status == FileStatus.draft:
        file.status = FileStatus.approved

    db.add(file)
    db.commit()
    db.refresh(file)

    return old_status, _enum_value(file.status)


def scan_file(
    db: Session,
    file_id: str,
    scanner_agent_id: str | None = None,
) -> dict:
    file = db.query(File).filter(File.id == file_id).first()
    if not file:
        return {
            "status": "error",
            "message": "file_not_found",
            "findings": [],
        }

    log_event(
        db=db,
        actor_agent_id=scanner_agent_id,
        action="scan_file",
        resource_type="file",
        resource_id=file.id,
        severity=AuditSeverity.info,
        details={
            "filename": file.name,
            "scanner": "regex-security-scanner",
        },
    )

    try:
        content = _decrypt_file_content(file)
    except Exception as exc:
        log_event(
            db=db,
            actor_agent_id=scanner_agent_id,
            action="security_scan_failed",
            resource_type="file",
            resource_id=file.id,
            status="failed",
            severity=AuditSeverity.high,
            reason=str(exc),
            details={
                "filename": file.name,
                "object_key": file.object_key,
            },
        )

        emit_workspace_updated(
            event_type="security_scan_failed",
            message="Security scan failed",
            payload={
                **_file_realtime_payload(file, scanner_agent_id),
                "reason": str(exc),
            },
        )

        return {
            "status": "error",
            "message": "scan_failed",
            "reason": str(exc),
            "file_id": file.id,
            "findings": [],
        }

    matched_patterns = _match_patterns(content)
    findings = _create_missing_findings(
        db=db,
        file=file,
        matched_patterns=matched_patterns,
    )
    should_quarantine = _should_quarantine(findings)

    old_status, new_status = _update_file_status_after_scan(
        db=db,
        file=file,
        should_quarantine=should_quarantine,
    )

    if should_quarantine:
        log_event(
            db=db,
            actor_agent_id=scanner_agent_id,
            action="quarantine_file",
            resource_type="file",
            resource_id=file.id,
            severity=AuditSeverity.high,
            reason="high_or_critical_security_finding_detected",
            details={
                "old_status": old_status,
                "new_status": new_status,
                "findings": findings,
            },
        )

        emit_workspace_updated(
            event_type="file_quarantined",
            message="File quarantined after security scan",
            payload={
                **_file_realtime_payload(file, scanner_agent_id),
                "old_status": old_status,
                "new_status": new_status,
                "findings_count": len(findings),
                "new_findings_count": len([finding for finding in findings if finding.get("is_new")]),
            },
        )
    else:
        log_event(
            db=db,
            actor_agent_id=scanner_agent_id,
            action="security_scan_passed",
            resource_type="file",
            resource_id=file.id,
            severity=AuditSeverity.info,
            details={
                "old_status": old_status,
                "new_status": new_status,
                "findings_count": len(findings),
                "new_findings_count": len([finding for finding in findings if finding.get("is_new")]),
            },
        )

        emit_workspace_updated(
            event_type="security_scan_finished",
            message="Security scan finished",
            payload={
                **_file_realtime_payload(file, scanner_agent_id),
                "old_status": old_status,
                "new_status": new_status,
                "findings_count": len(findings),
                "new_findings_count": len([finding for finding in findings if finding.get("is_new")]),
            },
        )

    return {
        "status": "completed",
        "file_id": file.id,
        "file_status": new_status,
        "findings": [
            {key: value for key, value in finding.items() if key != "quarantine"}
            for finding in findings
        ],
        "quarantined": should_quarantine,
    }


def release_from_quarantine(
    db: Session,
    file_id: str,
    released_by_agent_id: str | None = None,
    reason: str | None = None,
) -> File:
    file = db.query(File).filter(File.id == file_id).first()
    if not file:
        raise ValueError("file_not_found")

    old_status = _enum_value(file.status)

    if file.status != FileStatus.quarantined:
        log_event(
            db=db,
            actor_agent_id=released_by_agent_id,
            action="release_from_quarantine_skipped",
            resource_type="file",
            resource_id=file.id,
            severity=AuditSeverity.info,
            reason="file_is_not_quarantined",
            details={
                "old_status": old_status,
                "requested_reason": reason,
            },
        )

        emit_workspace_updated(
            event_type="file_release_skipped",
            message="File release skipped because file is not quarantined",
            payload={
                **_file_realtime_payload(file, released_by_agent_id),
                "old_status": old_status,
                "reason": "file_is_not_quarantined",
            },
        )
        return file

    file.status = FileStatus.approved

    db.add(file)
    db.commit()
    db.refresh(file)

    log_event(
        db=db,
        actor_agent_id=released_by_agent_id,
        action="release_from_quarantine",
        resource_type="file",
        resource_id=file.id,
        severity=AuditSeverity.warning,
        reason=reason,
        details={
            "old_status": old_status,
            "new_status": _enum_value(file.status),
        },
    )

    emit_workspace_updated(
        event_type="file_released",
        message="File released from quarantine",
        payload={
            **_file_realtime_payload(file, released_by_agent_id),
            "old_status": old_status,
            "new_status": _enum_value(file.status),
            "reason": reason,
        },
    )

    return file