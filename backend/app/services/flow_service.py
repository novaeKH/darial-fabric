import csv
import io
import json
from datetime import datetime
from typing import Any

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.models.base import (
    Agent,
    AuditSeverity,
    File,
    FileLineage,
    FlowRun,
    Folder,
)
from app.services.audit_service import log_event
from app.services.file_service import read_file_as_agent, upload_file_as_agent
from app.services.permission_service import grant_permission
from app.services.realtime_service import emit_workspace_updated
from app.services.security_scanner import scan_file


FLOW_NAME = "dataset-processing-flow"
TEMP_ACCESS_MINUTES = 30


def _enum_value(value: object) -> str:
    return getattr(value, "value", str(value))


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat()


def _make_upload_file(filename: str, data: bytes) -> UploadFile:
    return UploadFile(
        filename=filename,
        file=io.BytesIO(data),
    )


def _file_metadata(file: File) -> dict[str, Any]:
    return file.metadata_json or {}


def _source_display_name(source_file: File) -> str:
    metadata = _file_metadata(source_file)
    if metadata.get("display_name"):
        return str(metadata["display_name"])

    name = source_file.name
    if "server_metrics" in name:
        return "Метрики серверов"
    if "security_events" in name:
        return "События безопасности"
    if "business_events" in name:
        return "Бизнес-события"

    return name


def _file_realtime_payload(file: File) -> dict[str, Any]:
    metadata = _file_metadata(file)
    return {
        "file_id": file.id,
        "filename": file.name,
        "display_name": metadata.get("display_name") or _source_display_name(file),
        "display_type": metadata.get("display_type"),
        "status": _enum_value(file.status),
        "classification": _enum_value(file.classification),
        "owner_agent_id": file.owner_agent_id,
        "created_by_flow_id": file.created_by_flow_id,
    }


def _derived_metadata(
    source_file: File,
    display_name: str,
    display_type: str,
    description: str,
    artifact_type: str,
) -> dict[str, Any]:
    source_metadata = _file_metadata(source_file)

    return {
        "display_name": display_name,
        "display_type": display_type,
        "description": description,
        "artifact_type": artifact_type,
        "source_file_id": source_file.id,
        "source_file_name": source_file.name,
        "source_display_name": _source_display_name(source_file),
        "source_dataset_type": source_metadata.get("dataset_type"),
        "scenario": source_metadata.get("scenario"),
        "generated_by_flow": FLOW_NAME,
    }


def _apply_file_metadata(db: Session, file: File, metadata: dict[str, Any]) -> None:
    current_metadata = file.metadata_json or {}
    file.metadata_json = {
        **current_metadata,
        **metadata,
        "original_filename": file.name,
    }
    db.add(file)
    db.commit()
    db.refresh(file)


def _get_agent(db: Session, name: str) -> Agent | None:
    return db.query(Agent).filter(Agent.name == name).first()


def _get_folder(db: Session, name: str) -> Folder | None:
    return db.query(Folder).filter(Folder.name == name).first()


def _create_lineage(
    db: Session,
    source_file_id: str,
    derived_file_id: str,
    flow_run_id: str,
    created_by_agent_id: str,
) -> FileLineage:
    lineage = FileLineage(
        source_file_id=source_file_id,
        derived_file_id=derived_file_id,
        flow_run_id=flow_run_id,
        created_by_agent_id=created_by_agent_id,
    )
    db.add(lineage)
    db.commit()
    db.refresh(lineage)
    return lineage


def _create_flow_run(
    db: Session,
    name: str,
    started_by_agent_id: str | None,
    details: dict[str, Any] | None = None,
) -> FlowRun:
    flow_run = FlowRun(
        name=name,
        status="running",
        started_by_agent_id=started_by_agent_id,
        details=details or {},
    )
    db.add(flow_run)
    db.commit()
    db.refresh(flow_run)

    log_event(
        db=db,
        actor_agent_id=started_by_agent_id,
        action="flow_started",
        resource_type="flow_run",
        resource_id=flow_run.id,
        details={
            "name": name,
            "details": details or {},
        },
    )

    emit_workspace_updated(
        event_type="flow_started",
        message="Processing flow started",
        payload={
            "flow_run_id": flow_run.id,
            "flow_name": flow_run.name,
            "status": flow_run.status,
            "started_by_agent_id": started_by_agent_id,
            "details": details or {},
        },
    )

    return flow_run


def _finish_flow_run(
    db: Session,
    flow_run: FlowRun,
    status: str,
    details: dict[str, Any] | None = None,
) -> None:
    flow_run.status = status
    flow_run.details = {
        **(flow_run.details or {}),
        **(details or {}),
        "finished_at": _utc_now_iso(),
    }

    db.add(flow_run)
    db.commit()
    db.refresh(flow_run)

    severity = AuditSeverity.info if status == "completed" else AuditSeverity.warning

    log_event(
        db=db,
        actor_agent_id=flow_run.started_by_agent_id,
        action="flow_finished",
        resource_type="flow_run",
        resource_id=flow_run.id,
        status=status,
        severity=severity,
        details=flow_run.details,
    )

    emit_workspace_updated(
        event_type="flow_finished" if status == "completed" else "flow_failed",
        message="Processing flow finished" if status == "completed" else "Processing flow failed",
        payload={
            "flow_run_id": flow_run.id,
            "flow_name": flow_run.name,
            "status": flow_run.status,
            "started_by_agent_id": flow_run.started_by_agent_id,
            "details": flow_run.details,
        },
    )


def _parse_csv_rows(data: bytes) -> list[dict[str, str]]:
    text = data.decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


def _row_contains_any(row: dict[str, Any], words: tuple[str, ...]) -> bool:
    row_text = json.dumps(row, ensure_ascii=False).lower()
    return any(word in row_text for word in words)


def _build_processed_dataset(source_name: str, rows: list[dict[str, Any]]) -> bytes:
    """
    Simplified processing:
    - keep original fields;
    - add source_name;
    - add processed_at;
    - add row_quality.
    """
    processed_at = _utc_now_iso()

    if not rows:
        content = "source_name,processed_at,row_quality,note\n"
        content += f"{source_name},{processed_at},empty,no rows found\n"
        return content.encode("utf-8")

    processed_rows: list[dict[str, Any]] = []

    for row in rows:
        new_row = dict(row)
        new_row["source_name"] = source_name
        new_row["processed_at"] = processed_at
        new_row["row_quality"] = "ok"

        if _row_contains_any(row, ("anomaly", "suspicious", "critical")):
            new_row["row_quality"] = "requires_review"

        processed_rows.append(new_row)

    headers = list(processed_rows[0].keys())

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers)
    writer.writeheader()
    writer.writerows(processed_rows)

    return buffer.getvalue().encode("utf-8")


def _build_research_summary(source_file: File, rows: list[dict[str, Any]]) -> bytes:
    total_rows = len(rows)
    suspicious_rows = sum(
        1 for row in rows if _row_contains_any(row, ("suspicious", "critical"))
    )
    anomaly_rows = sum(1 for row in rows if _row_contains_any(row, ("anomaly",)))

    report = {
        "report_type": "research_summary",
        "source_file_id": source_file.id,
        "source_file_name": source_file.name,
        "source_display_name": _source_display_name(source_file),
        "created_at": _utc_now_iso(),
        "total_rows": total_rows,
        "suspicious_rows": suspicious_rows,
        "anomaly_rows": anomaly_rows,
        "summary": "Датасет автоматически проанализирован research-agent.",
        "recommendation": "Проверьте аномалии, если suspicious_rows или anomaly_rows больше нуля.",
    }

    return json.dumps(report, indent=2, ensure_ascii=False).encode("utf-8")


def _build_qa_report(source_file: File, rows: list[dict[str, Any]]) -> bytes:
    total_rows = len(rows)
    empty_values = sum(
        1
        for row in rows
        for value in row.values()
        if value is None or str(value).strip() == ""
    )

    status = "passed"
    if total_rows == 0 or empty_values > 0:
        status = "requires_review"

    report = {
        "report_type": "qa_report",
        "source_file_id": source_file.id,
        "source_file_name": source_file.name,
        "source_display_name": _source_display_name(source_file),
        "created_at": _utc_now_iso(),
        "total_rows": total_rows,
        "empty_values": empty_values,
        "qa_status": status,
        "checks": [
            "file_readable",
            "csv_parseable",
            "empty_values_check",
            "basic_quality_check",
        ],
    }

    return json.dumps(report, indent=2, ensure_ascii=False).encode("utf-8")


def _grant_temporary_read_access(
    db: Session,
    subject_agent_id: str,
    resource_id: str,
    granted_by_agent_id: str,
    reason: str,
) -> None:
    grant_permission(
        db=db,
        subject_agent_id=subject_agent_id,
        resource_type="file",
        resource_id=resource_id,
        action="read",
        expires_in_minutes=TEMP_ACCESS_MINUTES,
        reason=reason,
        granted_by_agent_id=granted_by_agent_id,
    )


def _upload_derived_file(
    db: Session,
    agent: Agent,
    folder: Folder,
    filename: str,
    data: bytes,
    classification: str,
    source_file: File,
    flow_run: FlowRun,
    metadata: dict[str, Any],
) -> File:
    derived_file = upload_file_as_agent(
        db=db,
        agent_id=agent.id,
        folder_id=folder.id,
        upload=_make_upload_file(filename, data),
        classification=classification,
    )

    derived_file.created_by_flow_id = flow_run.id
    db.add(derived_file)
    db.commit()
    db.refresh(derived_file)

    _apply_file_metadata(db, derived_file, metadata)

    _create_lineage(
        db=db,
        source_file_id=source_file.id,
        derived_file_id=derived_file.id,
        flow_run_id=flow_run.id,
        created_by_agent_id=agent.id,
    )

    emit_workspace_updated(
        event_type="derived_file_created",
        message="Derived file created by processing flow",
        payload={
            "flow_run_id": flow_run.id,
            "source_file": _file_realtime_payload(source_file),
            "derived_file": _file_realtime_payload(derived_file),
            "created_by_agent_id": agent.id,
            "created_by_agent_name": agent.name,
        },
    )

    return derived_file


def _scan_and_fail_if_quarantined(
    db: Session,
    file: File,
    security_agent: Agent,
) -> dict:
    scan_result = scan_file(
        db=db,
        file_id=file.id,
        scanner_agent_id=security_agent.id,
    )

    if scan_result.get("quarantined"):
        raise RuntimeError(f"File was quarantined during flow: {file.id}")

    return scan_result


def _resolve_required_entities(db: Session) -> dict[str, Agent | Folder]:
    entities: dict[str, Agent | Folder | None] = {
        "data-agent": _get_agent(db, "data-agent"),
        "research-agent": _get_agent(db, "research-agent"),
        "qa-agent": _get_agent(db, "qa-agent"),
        "security-agent": _get_agent(db, "security-agent"),
        "processed folder": _get_folder(db, "processed"),
        "research folder": _get_folder(db, "research"),
        "qa folder": _get_folder(db, "qa"),
    }

    missing = [name for name, value in entities.items() if value is None]
    if missing:
        raise RuntimeError(f"Missing required entities: {', '.join(missing)}")

    return entities  # type: ignore[return-value]


def run_processing_flow_for_file(
    db: Session,
    source_file_id: str,
) -> dict:
    """
    Main automatic flow:
    incoming file
    -> processed dataset
    -> research summary
    -> QA report
    """
    source_file = db.query(File).filter(File.id == source_file_id).first()
    if not source_file:
        emit_workspace_updated(
            event_type="flow_failed",
            message="Processing flow failed: source file not found",
            payload={
                "source_file_id": source_file_id,
                "error": "source_file_not_found",
            },
        )
        return {
            "status": "error",
            "message": "source_file_not_found",
        }

    try:
        entities = _resolve_required_entities(db)
    except RuntimeError as exc:
        emit_workspace_updated(
            event_type="flow_failed",
            message="Processing flow failed: missing required entities",
            payload={
                "source_file_id": source_file_id,
                "error": str(exc),
            },
        )
        return {
            "status": "error",
            "message": "missing_required_entities",
            "error": str(exc),
        }

    data_agent = entities["data-agent"]
    research_agent = entities["research-agent"]
    qa_agent = entities["qa-agent"]
    security_agent = entities["security-agent"]
    processed_folder = entities["processed folder"]
    research_folder = entities["research folder"]
    qa_folder = entities["qa folder"]

    flow_run = _create_flow_run(
        db=db,
        name=FLOW_NAME,
        started_by_agent_id=data_agent.id,
        details={
            "source_file_id": source_file.id,
            "source_file_name": source_file.name,
            "source_display_name": _source_display_name(source_file),
        },
    )

    try:
        _scan_and_fail_if_quarantined(
            db=db,
            file=source_file,
            security_agent=security_agent,
        )

        _grant_temporary_read_access(
            db=db,
            subject_agent_id=data_agent.id,
            resource_id=source_file.id,
            granted_by_agent_id=security_agent.id,
            reason="Сценарию обработки данных нужен временный доступ на чтение исходного файла.",
        )

        _, source_data = read_file_as_agent(
            db=db,
            agent_id=data_agent.id,
            file_id=source_file.id,
        )
        rows = _parse_csv_rows(source_data)

        processed_data = _build_processed_dataset(source_file.name, rows)
        processed_file = _upload_derived_file(
            db=db,
            agent=data_agent,
            folder=processed_folder,
            filename=f"processed_{source_file.name}",
            data=processed_data,
            classification=_enum_value(source_file.classification),
            source_file=source_file,
            flow_run=flow_run,
            metadata=_derived_metadata(
                source_file=source_file,
                display_name=f"Обработанный датасет: {_source_display_name(source_file)}",
                display_type="Обработанный датасет",
                description="Файл создан data-agent: исходные строки дополнены служебными полями source_name, processed_at и row_quality.",
                artifact_type="processed_dataset",
            ),
        )

        _scan_and_fail_if_quarantined(
            db=db,
            file=processed_file,
            security_agent=security_agent,
        )

        _grant_temporary_read_access(
            db=db,
            subject_agent_id=research_agent.id,
            resource_id=processed_file.id,
            granted_by_agent_id=security_agent.id,
            reason="Research-agent нужен временный доступ к обработанному датасету для формирования аналитической сводки.",
        )

        _, processed_plain_data = read_file_as_agent(
            db=db,
            agent_id=research_agent.id,
            file_id=processed_file.id,
        )
        processed_rows = _parse_csv_rows(processed_plain_data)

        research_file = _upload_derived_file(
            db=db,
            agent=research_agent,
            folder=research_folder,
            filename=f"summary_{processed_file.name}.json",
            data=_build_research_summary(processed_file, processed_rows),
            classification="internal",
            source_file=processed_file,
            flow_run=flow_run,
            metadata=_derived_metadata(
                source_file=processed_file,
                display_name=f"Исследовательская сводка: {_source_display_name(source_file)}",
                display_type="Исследовательская сводка",
                description="JSON-отчёт, созданный research-agent: количество строк, подозрительные записи, аномалии и рекомендация.",
                artifact_type="research_summary",
            ),
        )

        _scan_and_fail_if_quarantined(
            db=db,
            file=research_file,
            security_agent=security_agent,
        )

        _grant_temporary_read_access(
            db=db,
            subject_agent_id=qa_agent.id,
            resource_id=processed_file.id,
            granted_by_agent_id=security_agent.id,
            reason="QA-agent нужен временный доступ к обработанному датасету для проверки качества данных.",
        )

        _, qa_source_data = read_file_as_agent(
            db=db,
            agent_id=qa_agent.id,
            file_id=processed_file.id,
        )
        qa_rows = _parse_csv_rows(qa_source_data)

        qa_file = _upload_derived_file(
            db=db,
            agent=qa_agent,
            folder=qa_folder,
            filename=f"qa_report_{processed_file.name}.json",
            data=_build_qa_report(processed_file, qa_rows),
            classification="internal",
            source_file=processed_file,
            flow_run=flow_run,
            metadata=_derived_metadata(
                source_file=processed_file,
                display_name=f"QA-отчёт: {_source_display_name(source_file)}",
                display_type="QA-отчёт",
                description="JSON-отчёт, созданный qa-agent: проверка читаемости, парсинга CSV, пустых значений и базового качества данных.",
                artifact_type="qa_report",
            ),
        )

        _scan_and_fail_if_quarantined(
            db=db,
            file=qa_file,
            security_agent=security_agent,
        )

        _finish_flow_run(
            db=db,
            flow_run=flow_run,
            status="completed",
            details={
                "source_file_id": source_file.id,
                "source_display_name": _source_display_name(source_file),
                "processed_file_id": processed_file.id,
                "research_file_id": research_file.id,
                "qa_file_id": qa_file.id,
            },
        )

        emit_workspace_updated(
            event_type="flow_artifacts_ready",
            message="Processing flow artifacts are ready",
            payload={
                "flow_run_id": flow_run.id,
                "source_file": _file_realtime_payload(source_file),
                "processed_file": _file_realtime_payload(processed_file),
                "research_file": _file_realtime_payload(research_file),
                "qa_file": _file_realtime_payload(qa_file),
            },
        )

        return {
            "status": "completed",
            "flow_run_id": flow_run.id,
            "source_file_id": source_file.id,
            "source_display_name": _source_display_name(source_file),
            "processed_file_id": processed_file.id,
            "research_file_id": research_file.id,
            "qa_file_id": qa_file.id,
        }

    except Exception as exc:
        _finish_flow_run(
            db=db,
            flow_run=flow_run,
            status="failed",
            details={
                "source_file_id": source_file.id,
                "source_display_name": _source_display_name(source_file),
                "error": str(exc),
            },
        )

        return {
            "status": "failed",
            "flow_run_id": flow_run.id,
            "source_file_id": source_file.id,
            "source_display_name": _source_display_name(source_file),
            "error": str(exc),
        }