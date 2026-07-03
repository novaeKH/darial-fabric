from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.base import (
    Agent,
    File,
    FileLineage,
    Folder,
    Permission,
    SecurityFinding,
    Team,
    Workspace,
)


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


def _node_id(node_type: str, raw_id: str | None) -> str:
    return f"{node_type}:{raw_id}"


def _edge_id(edge_type: str, source: str, target: str, suffix: str | None = None) -> str:
    parts = [edge_type, source, target]
    if suffix:
        parts.append(suffix)
    return "::".join(parts)


def _add_edge(
    edges: list[dict[str, Any]],
    edge_type: str,
    source: str,
    target: str,
    label: str | None = None,
    **extra: Any,
) -> None:
    if not source or not target:
        return

    edge = {
        "id": _edge_id(edge_type, source, target, extra.get("id")),
        "source": source,
        "target": target,
        "type": edge_type,
    }

    if label:
        edge["label"] = label

    edge.update(extra)
    edges.append(edge)


def _agent_node(agent: Agent) -> dict[str, Any]:
    return {
        "id": _node_id("agent", agent.id),
        "raw_id": agent.id,
        "label": agent.name,
        "type": "agent",
        "role": agent.role,
        "risk_level": _enum_value(agent.risk_level),
        "clearance_level": _enum_value(agent.clearance_level),
        "autonomy_level": agent.autonomy_level,
        "status": agent.status,
        "created_at": _iso(agent.created_at),
    }


def _file_node(
    file: File,
    agent_name_by_id: dict[str, str],
    finding_count_by_file_id: dict[str, int],
) -> dict[str, Any]:
    return {
        "id": _node_id("file", file.id),
        "raw_id": file.id,
        "label": _display_name_for_file(file) or file.name,
        "technical_name": file.name,
        "display_name": _display_name_for_file(file),
        "display_type": _display_type_for_file(file),
        "description": _description_for_file(file),
        "type": "file",
        "status": _enum_value(file.status),
        "classification": _enum_value(file.classification),
        "size": file.size,
        "content_hash": file.content_hash,
        "owner_agent_id": file.owner_agent_id,
        "owner_agent_name": agent_name_by_id.get(file.owner_agent_id),
        "findings_count": finding_count_by_file_id.get(file.id, 0),
        "folder_id": file.folder_id,
        "workspace_id": file.workspace_id,
        "created_by_flow_id": file.created_by_flow_id,
        "metadata": {
            "dataset_type": _file_metadata(file).get("dataset_type"),
            "artifact_type": _file_metadata(file).get("artifact_type"),
            "scenario": _file_metadata(file).get("scenario"),
            "source": _file_metadata(file).get("source"),
            "source_display_name": _file_metadata(file).get("source_display_name"),
        },
        "created_at": _iso(file.created_at),
    }


def _permission_node(
    permission: Permission,
    agent_name_by_id: dict[str, str],
    file_name_by_id: dict[str, str],
    folder_name_by_id: dict[str, str],
) -> dict[str, Any]:
    action = _enum_value(permission.action)
    status = permission.status

    subject_type = _enum_value(permission.subject_type)
    resource_type = _enum_value(permission.resource_type)

    subject_name = None
    if subject_type == "agent":
        subject_name = agent_name_by_id.get(permission.subject_id)

    resource_label = None
    if resource_type == "file":
        resource_label = file_name_by_id.get(permission.resource_id)
    elif resource_type == "folder":
        resource_label = folder_name_by_id.get(permission.resource_id)

    return {
        "id": _node_id("permission", permission.id),
        "raw_id": permission.id,
        "label": f"{action} ({status})",
        "display_label": f"{action} · {status}",
        "type": "permission",
        "action": action,
        "status": status,
        "subject_type": subject_type,
        "subject_id": permission.subject_id,
        "subject_name": subject_name,
        "resource_type": resource_type,
        "resource_id": permission.resource_id,
        "resource_label": resource_label,
        "expires_at": _iso(permission.expires_at),
        "reason": permission.reason,
        "created_at": _iso(permission.created_at),
    }


def _permission_subject_node_id(permission: Permission) -> str:
    subject_type = _enum_value(permission.subject_type)
    return _node_id(subject_type, permission.subject_id)


def _permission_resource_node_id(permission: Permission) -> str:
    resource_type = _enum_value(permission.resource_type)
    return _node_id(resource_type, permission.resource_id)


def _agent_name_by_id(agents: list[Agent]) -> dict[str, str]:
    return {agent.id: agent.name for agent in agents}


def _folder_name_by_id(folders: list[Folder]) -> dict[str, str]:
    return {folder.id: folder.name for folder in folders}


def _file_label_by_id(files: list[File]) -> dict[str, str]:
    return {file.id: _display_name_for_file(file) or file.name for file in files}


def _finding_count_by_file_id(db: Session) -> dict[str, int]:
    findings = db.query(SecurityFinding).all()
    counts: dict[str, int] = {}

    for finding in findings:
        counts[finding.file_id] = counts.get(finding.file_id, 0) + 1

    return counts


def get_access_graph(db: Session) -> dict:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    teams = db.query(Team).order_by(Team.created_at.asc()).all()
    agents = db.query(Agent).order_by(Agent.created_at.asc()).all()
    workspaces = db.query(Workspace).order_by(Workspace.created_at.asc()).all()
    folders = db.query(Folder).order_by(Folder.created_at.asc()).all()
    files = db.query(File).order_by(File.created_at.asc()).all()
    permissions = db.query(Permission).order_by(Permission.created_at.asc()).all()
    lineage = db.query(FileLineage).order_by(FileLineage.created_at.asc()).all()

    agent_names = _agent_name_by_id(agents)
    folder_names = _folder_name_by_id(folders)
    file_labels = _file_label_by_id(files)
    finding_counts = _finding_count_by_file_id(db)

    known_node_ids: set[str] = set()

    def add_node(node: dict[str, Any]) -> None:
        if node["id"] in known_node_ids:
            return
        known_node_ids.add(node["id"])
        nodes.append(node)

    for team in teams:
        add_node(
            {
                "id": _node_id("team", team.id),
                "raw_id": team.id,
                "label": team.name,
                "type": "team",
                "created_at": _iso(team.created_at),
            }
        )

    for agent in agents:
        add_node(_agent_node(agent))

        _add_edge(
            edges=edges,
            edge_type="has_agent",
            source=_node_id("team", agent.team_id),
            target=_node_id("agent", agent.id),
            label="агент",
        )

    for workspace in workspaces:
        add_node(
            {
                "id": _node_id("workspace", workspace.id),
                "raw_id": workspace.id,
                "label": workspace.name,
                "type": "workspace",
                "team_id": workspace.team_id,
                "created_at": _iso(workspace.created_at),
            }
        )

        _add_edge(
            edges=edges,
            edge_type="owns_workspace",
            source=_node_id("team", workspace.team_id),
            target=_node_id("workspace", workspace.id),
            label="владеет",
        )

    for folder in folders:
        add_node(
            {
                "id": _node_id("folder", folder.id),
                "raw_id": folder.id,
                "label": folder.name,
                "type": "folder",
                "workspace_id": folder.workspace_id,
                "parent_folder_id": folder.parent_folder_id,
                "parent_folder_name": folder_names.get(folder.parent_folder_id),
                "created_at": _iso(folder.created_at),
            }
        )

        if folder.parent_folder_id:
            source = _node_id("folder", folder.parent_folder_id)
        else:
            source = _node_id("workspace", folder.workspace_id)

        _add_edge(
            edges=edges,
            edge_type="contains_folder",
            source=source,
            target=_node_id("folder", folder.id),
            label="содержит",
        )

    for file in files:
        add_node(_file_node(file, agent_names, finding_counts))

        _add_edge(
            edges=edges,
            edge_type="contains_file",
            source=_node_id("folder", file.folder_id),
            target=_node_id("file", file.id),
            label="содержит",
        )

        _add_edge(
            edges=edges,
            edge_type="owns_file",
            source=_node_id("agent", file.owner_agent_id),
            target=_node_id("file", file.id),
            label="владеет файлом",
        )

    for permission in permissions:
        permission_node_id = _node_id("permission", permission.id)
        add_node(_permission_node(permission, agent_names, file_labels, folder_names))

        subject_node_id = _permission_subject_node_id(permission)
        resource_node_id = _permission_resource_node_id(permission)

        _add_edge(
            edges=edges,
            edge_type="has_permission",
            source=subject_node_id,
            target=permission_node_id,
            label="имеет доступ",
            id=permission.id,
        )

        _add_edge(
            edges=edges,
            edge_type="grants_access_to",
            source=permission_node_id,
            target=resource_node_id,
            label=_enum_value(permission.action),
            id=permission.id,
            status=permission.status,
            subject_name=agent_names.get(permission.subject_id),
            resource_label=file_labels.get(permission.resource_id) if _enum_value(permission.resource_type) == "file" else folder_names.get(permission.resource_id),
            expires_at=_iso(permission.expires_at),
        )

    for item in lineage:
        _add_edge(
            edges=edges,
            edge_type="derived_from",
            source=_node_id("file", item.source_file_id),
            target=_node_id("file", item.derived_file_id),
            label="создано из",
            id=item.id,
            flow_run_id=item.flow_run_id,
            created_by_agent_id=item.created_by_agent_id,
            created_at=_iso(item.created_at),
        )

    visible_node_ids = {node["id"] for node in nodes}
    visible_edges = [
        edge
        for edge in edges
        if edge["source"] in visible_node_ids and edge["target"] in visible_node_ids
    ]

    return {
        "nodes": nodes,
        "edges": visible_edges,
        "summary": {
            "nodes_count": len(nodes),
            "edges_count": len(visible_edges),
            "teams": len(teams),
            "agents": len(agents),
            "workspaces": len(workspaces),
            "folders": len(folders),
            "files": len(files),
            "permissions": len(permissions),
            "lineage_edges": len(lineage),
            "security_findings": sum(finding_counts.values()),
        },
    }