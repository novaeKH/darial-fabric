import io

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.base import Agent, AuditSeverity, File, FileStatus, Folder
from app.services.audit_service import log_event
from app.services.file_service import upload_file_as_agent
from app.services.flow_service import run_processing_flow_for_file
from app.services.security_scanner import scan_file
from app.services.synthetic_data_service import generate_random_dataset


SYNTHETIC_AGENT_NAME = "synthetic-data-agent"
SECURITY_AGENT_NAME = "security-agent"
INCOMING_FOLDER_NAME = "incoming"


def _enum_value(value: object) -> str:
    return getattr(value, "value", str(value))


def _make_upload_file(filename: str, data: bytes) -> UploadFile:
    """Create an in-memory UploadFile for generated synthetic data."""
    return UploadFile(
        filename=filename,
        file=io.BytesIO(data),
    )


def _find_agent(db: Session, name: str) -> Agent | None:
    return db.query(Agent).filter(Agent.name == name).first()


def _find_folder(db: Session, name: str) -> Folder | None:
    return db.query(Folder).filter(Folder.name == name).first()


def _find_synthetic_agent(db: Session) -> Agent | None:
    return _find_agent(db, SYNTHETIC_AGENT_NAME)


def _find_security_agent(db: Session) -> Agent | None:
    return _find_agent(db, SECURITY_AGENT_NAME)


def _find_incoming_folder(db: Session) -> Folder | None:
    return _find_folder(db, INCOMING_FOLDER_NAME)


def cleanup_old_synthetic_files(db: Session) -> dict:
    """
    Archive old synthetic files after the configured limit.

    The files are not deleted because lineage, audit and demo visibility are more
    useful than hard deletion in the MVP.
    """
    max_files = max(int(settings.SYNTHETIC_AGENT_MAX_FILES), 0)

    files = (
        db.query(File)
        .join(Agent, File.owner_agent_id == Agent.id)
        .filter(Agent.name == SYNTHETIC_AGENT_NAME)
        .filter(File.status != FileStatus.archived)
        .order_by(File.created_at.desc())
        .all()
    )

    if len(files) <= max_files:
        return {
            "status": "skipped",
            "archived_count": 0,
            "active_synthetic_files": len(files),
            "max_files": max_files,
        }

    old_files = files[max_files:]

    for file in old_files:
        file.status = FileStatus.archived
        db.add(file)

    db.commit()

    return {
        "status": "completed",
        "archived_count": len(old_files),
        "active_synthetic_files": max_files,
        "max_files": max_files,
    }


def _attach_synthetic_metadata(
    db: Session,
    file: File,
    metadata: dict,
) -> File:
    file.metadata_json = {
        **(file.metadata_json or {}),
        **metadata,
        "generated_by": SYNTHETIC_AGENT_NAME,
        "generator": "synthetic_data_service.generate_random_dataset",
    }

    db.add(file)
    db.commit()
    db.refresh(file)

    return file


def _log_synthetic_generation_event(
    db: Session,
    synthetic_agent: Agent,
    uploaded_file: File,
    metadata: dict,
) -> None:
    log_event(
        db=db,
        actor_agent_id=synthetic_agent.id,
        action="synthetic_dataset_generated",
        resource_type="file",
        resource_id=uploaded_file.id,
        severity=AuditSeverity.info,
        details={
            "filename": uploaded_file.name,
            "file_status": _enum_value(uploaded_file.status),
            "metadata": metadata,
        },
    )


def run_synthetic_generation_once(db: Session) -> dict:
    synthetic_agent = _find_synthetic_agent(db)
    if not synthetic_agent:
        return {
            "status": "error",
            "message": f"{SYNTHETIC_AGENT_NAME} not found. Run demo reset or seed first.",
        }

    if synthetic_agent.status != "active":
        return {
            "status": "error",
            "message": f"{SYNTHETIC_AGENT_NAME} is not active.",
        }

    security_agent = _find_security_agent(db)
    incoming_folder = _find_incoming_folder(db)

    if not incoming_folder:
        return {
            "status": "error",
            "message": f"{INCOMING_FOLDER_NAME} folder not found. Run demo reset or seed first.",
        }

    filename, data, metadata = generate_random_dataset()

    uploaded_file = upload_file_as_agent(
        db=db,
        agent_id=synthetic_agent.id,
        folder_id=incoming_folder.id,
        upload=_make_upload_file(filename, data),
        classification="internal",
    )

    uploaded_file = _attach_synthetic_metadata(
        db=db,
        file=uploaded_file,
        metadata=metadata,
    )

    _log_synthetic_generation_event(
        db=db,
        synthetic_agent=synthetic_agent,
        uploaded_file=uploaded_file,
        metadata=metadata,
    )

    scan_result = scan_file(
        db=db,
        file_id=uploaded_file.id,
        scanner_agent_id=security_agent.id if security_agent else None,
    )

    db.refresh(uploaded_file)

    flow_result = None
    if uploaded_file.status != FileStatus.quarantined:
        flow_result = run_processing_flow_for_file(
            db=db,
            source_file_id=uploaded_file.id,
        )

    cleanup_result = cleanup_old_synthetic_files(db)

    return {
        "status": "ok",
        "file_id": uploaded_file.id,
        "filename": uploaded_file.name,
        "file_status": _enum_value(uploaded_file.status),
        "metadata": metadata,
        "scan_result": scan_result,
        "flow_result": flow_result,
        "cleanup_result": cleanup_result,
    }