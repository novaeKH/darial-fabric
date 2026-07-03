from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.models.base import (
    Agent,
    AuditSeverity,
    ClearanceLevel,
    File,
    FileStatus,
    Folder,
    PermissionAction,
)
from app.services.audit_service import log_event
from app.services.encryption_service import decrypt_bytes, encrypt_bytes
from app.services.policy_engine import evaluate_file_access
from app.services.realtime_service import emit_workspace_updated
from app.services.storage_service import read_encrypted_file, save_encrypted_file


ENCRYPTION_ALGORITHM = "AES-256-GCM"
DEK_WRAPPING = "local-KEK"


def _safe_filename(upload: UploadFile) -> str:
    filename = upload.filename or "uploaded_file"
    return filename.replace("/", "_").replace("\\", "_")


def _enum_value(value: object) -> str:
    return getattr(value, "value", str(value))


def _file_display_name(file: File) -> str | None:
    metadata = file.metadata_json or {}
    return metadata.get("display_name")


def _file_display_type(file: File) -> str | None:
    metadata = file.metadata_json or {}
    return metadata.get("display_type")


def _file_realtime_payload(file: File, agent: Agent | None = None) -> dict:
    return {
        "file_id": file.id,
        "filename": file.name,
        "display_name": _file_display_name(file),
        "display_type": _file_display_type(file),
        "status": _enum_value(file.status),
        "classification": _enum_value(file.classification),
        "owner_agent_id": file.owner_agent_id,
        "actor_agent_id": agent.id if agent else None,
        "actor_agent_name": agent.name if agent else None,
    }


def _get_active_agent(db: Session, agent_id: str) -> Agent:
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if agent.status != "active":
        raise HTTPException(status_code=403, detail="Agent is not active")

    return agent


def _get_folder(db: Session, folder_id: str) -> Folder:
    folder = db.query(Folder).filter(Folder.id == folder_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    return folder


def _get_file(db: Session, file_id: str) -> File:
    file = db.query(File).filter(File.id == file_id).first()
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    return file


def _parse_classification(classification: str) -> ClearanceLevel:
    try:
        return ClearanceLevel(classification)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid classification") from exc


def _read_and_decrypt_file(
    db: Session,
    agent: Agent,
    file: File,
    auth_mode: str,
) -> bytes:
    if not file.encrypted_dek or not file.nonce or not file.metadata_json:
        log_event(
            db=db,
            actor_agent_id=agent.id,
            action="decrypt_file_failed",
            resource_type="file",
            resource_id=file.id,
            status="failed",
            severity=AuditSeverity.critical,
            reason="File encryption metadata is missing",
            details={
                "auth_mode": auth_mode,
                "filename": file.name,
                "display_name": _file_display_name(file),
            },
        )
        raise HTTPException(status_code=500, detail="File encryption metadata is missing")

    dek_nonce = file.metadata_json.get("dek_nonce")
    if not dek_nonce:
        log_event(
            db=db,
            actor_agent_id=agent.id,
            action="decrypt_file_failed",
            resource_type="file",
            resource_id=file.id,
            status="failed",
            severity=AuditSeverity.critical,
            reason="DEK nonce is missing",
            details={
                "auth_mode": auth_mode,
                "filename": file.name,
                "display_name": _file_display_name(file),
            },
        )
        raise HTTPException(status_code=500, detail="DEK nonce is missing")

    try:
        encrypted_data = read_encrypted_file(file.object_key)
        return decrypt_bytes(
            encrypted_data=encrypted_data,
            encrypted_dek_b64=file.encrypted_dek,
            dek_nonce_b64=dek_nonce,
            file_nonce_b64=file.nonce,
        )
    except FileNotFoundError as exc:
        log_event(
            db=db,
            actor_agent_id=agent.id,
            action="read_file_failed",
            resource_type="file",
            resource_id=file.id,
            status="failed",
            severity=AuditSeverity.high,
            reason=str(exc),
            details={
                "auth_mode": auth_mode,
                "object_key": file.object_key,
                "filename": file.name,
                "display_name": _file_display_name(file),
            },
        )
        raise HTTPException(status_code=404, detail="Encrypted object not found") from exc
    except Exception as exc:
        log_event(
            db=db,
            actor_agent_id=agent.id,
            action="decrypt_file_failed",
            resource_type="file",
            resource_id=file.id,
            status="failed",
            severity=AuditSeverity.critical,
            reason=str(exc),
            details={
                "auth_mode": auth_mode,
                "object_key": file.object_key,
                "filename": file.name,
                "display_name": _file_display_name(file),
            },
        )
        raise HTTPException(status_code=500, detail="Failed to decrypt file") from exc


def upload_file_as_agent(
    db: Session,
    agent_id: str,
    folder_id: str,
    upload: UploadFile,
    classification: str = "internal",
) -> File:
    agent = _get_active_agent(db, agent_id)
    folder = _get_folder(db, folder_id)
    classification_enum = _parse_classification(classification)
    filename = _safe_filename(upload)

    plain_data = upload.file.read()
    if plain_data is None:
        plain_data = b""

    encrypted_payload = encrypt_bytes(plain_data)

    try:
        object_key = save_encrypted_file(
            encrypted_payload["encrypted_data"],
            filename,
        )
    except Exception as exc:
        log_event(
            db=db,
            actor_agent_id=agent.id,
            action="upload_file_failed",
            resource_type="folder",
            resource_id=folder.id,
            status="failed",
            severity=AuditSeverity.high,
            reason=str(exc),
            details={
                "filename": filename,
                "classification": _enum_value(classification_enum),
            },
        )
        raise HTTPException(status_code=500, detail="Failed to store encrypted file") from exc

    file = File(
        name=filename,
        workspace_id=folder.workspace_id,
        folder_id=folder.id,
        object_key=object_key,
        classification=classification_enum,
        status=FileStatus.draft,
        owner_agent_id=agent.id,
        encrypted_dek=encrypted_payload["encrypted_dek"],
        nonce=encrypted_payload["file_nonce"],
        content_hash=encrypted_payload["content_hash"],
        size=encrypted_payload["size"],
        metadata_json={
            "encryption": ENCRYPTION_ALGORITHM,
            "dek_wrapping": DEK_WRAPPING,
            "dek_nonce": encrypted_payload["dek_nonce"],
            "original_filename": upload.filename,
        },
    )

    db.add(file)
    db.commit()
    db.refresh(file)

    log_event(
        db=db,
        actor_agent_id=agent.id,
        action="upload_file",
        resource_type="file",
        resource_id=file.id,
        details={
            "filename": file.name,
            "classification": _enum_value(file.classification),
            "size": file.size,
            "folder_id": file.folder_id,
            "workspace_id": file.workspace_id,
            "auth_mode": "demo_agent_id",
        },
    )

    log_event(
        db=db,
        actor_agent_id=agent.id,
        action="encrypt_file",
        resource_type="file",
        resource_id=file.id,
        details={
            "algorithm": ENCRYPTION_ALGORITHM,
            "dek_per_file": True,
            "object_key": file.object_key,
            "auth_mode": "demo_agent_id",
        },
    )

    emit_workspace_updated(
        event_type="file_uploaded",
        message="File uploaded and encrypted",
        payload={
            **_file_realtime_payload(file, agent),
            "folder_id": file.folder_id,
            "workspace_id": file.workspace_id,
        },
    )

    return file


def read_file_as_agent(
    db: Session,
    agent_id: str,
    file_id: str,
    auth_mode: str = "demo_agent_id",
) -> tuple[File, bytes]:
    agent = _get_active_agent(db, agent_id)
    file = _get_file(db, file_id)

    access_decision = evaluate_file_access(
        db=db,
        agent=agent,
        file=file,
        action=PermissionAction.read,
    )

    if access_decision["decision"] != "allow":
        log_event(
            db=db,
            actor_agent_id=agent.id,
            action="deny_read_file",
            resource_type="file",
            resource_id=file.id,
            status="denied",
            severity=AuditSeverity.warning,
            reason=", ".join(access_decision["reasons"]),
            details={
                **access_decision,
                "auth_mode": auth_mode,
                "filename": file.name,
                "display_name": _file_display_name(file),
                "display_type": _file_display_type(file),
            },
        )

        emit_workspace_updated(
            event_type="file_read_denied",
            message="File read denied by policy",
            payload={
                **_file_realtime_payload(file, agent),
                "auth_mode": auth_mode,
                "reasons": access_decision["reasons"],
            },
        )

        raise HTTPException(
            status_code=403,
            detail={
                "message": "Access denied",
                "reasons": access_decision["reasons"],
                "auth_mode": auth_mode,
            },
        )

    plain_data = _read_and_decrypt_file(
        db=db,
        agent=agent,
        file=file,
        auth_mode=auth_mode,
    )

    log_event(
        db=db,
        actor_agent_id=agent.id,
        action="read_file",
        resource_type="file",
        resource_id=file.id,
        details={
            "filename": file.name,
            "display_name": _file_display_name(file),
            "display_type": _file_display_type(file),
            "size": file.size,
            "auth_mode": auth_mode,
        },
    )

    log_event(
        db=db,
        actor_agent_id=agent.id,
        action="decrypt_file",
        resource_type="file",
        resource_id=file.id,
        severity=AuditSeverity.warning,
        details={
            "algorithm": ENCRYPTION_ALGORITHM,
            "object_key": file.object_key,
            "auth_mode": auth_mode,
        },
    )

    emit_workspace_updated(
        event_type="file_read",
        message="File read and decrypted",
        payload={
            **_file_realtime_payload(file, agent),
            "auth_mode": auth_mode,
        },
    )

    return file, plain_data


def read_file_as_authenticated_agent(
    db: Session,
    authenticated_agent_id: str,
    file_id: str,
) -> tuple[File, bytes]:
    """
    Production-like read helper.

    authenticated_agent_id must come from verified X-Agent-Key, not from user-controlled query params.
    """
    return read_file_as_agent(
        db=db,
        agent_id=authenticated_agent_id,
        file_id=file_id,
        auth_mode="x_agent_key",
    )