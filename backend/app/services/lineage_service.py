from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.base import Agent, File, FileLineage


def _enum_value(value: object) -> str:
    return getattr(value, "value", str(value))


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _file_node_id(file_id: str) -> str:
    return f"file:{file_id}"


def _agent_name_by_id(db: Session, agent_ids: set[str | None]) -> dict[str, str]:
    clean_ids = {agent_id for agent_id in agent_ids if agent_id}
    if not clean_ids:
        return {}

    agents = db.query(Agent).filter(Agent.id.in_(clean_ids)).all()
    return {agent.id: agent.name for agent in agents}


def _file_by_id(db: Session, file_ids: set[str | None]) -> dict[str, File]:
    clean_ids = {file_id for file_id in file_ids if file_id}
    if not clean_ids:
        return {}

    files = db.query(File).filter(File.id.in_(clean_ids)).all()
    return {file.id: file for file in files}


def _serialize_file(file: File) -> dict[str, Any]:
    return {
        "id": file.id,
        "name": file.name,
        "status": _enum_value(file.status),
        "classification": _enum_value(file.classification),
        "owner_agent_id": file.owner_agent_id,
        "folder_id": file.folder_id,
        "workspace_id": file.workspace_id,
        "created_by_flow_id": file.created_by_flow_id,
        "size": file.size,
        "created_at": _iso(file.created_at),
    }


def _serialize_parent_item(
    item: FileLineage,
    files_by_id: dict[str, File],
    agent_names: dict[str, str],
) -> dict[str, Any]:
    source_file = files_by_id.get(item.source_file_id)

    return {
        "lineage_id": item.id,
        "source_file_id": item.source_file_id,
        "source_file_name": source_file.name if source_file else None,
        "source_file_status": _enum_value(source_file.status) if source_file else None,
        "source_file_classification": _enum_value(source_file.classification) if source_file else None,
        "flow_run_id": item.flow_run_id,
        "created_by_agent_id": item.created_by_agent_id,
        "created_by_agent_name": agent_names.get(item.created_by_agent_id),
        "created_at": _iso(item.created_at),
    }


def _serialize_child_item(
    item: FileLineage,
    files_by_id: dict[str, File],
    agent_names: dict[str, str],
) -> dict[str, Any]:
    derived_file = files_by_id.get(item.derived_file_id)

    return {
        "lineage_id": item.id,
        "derived_file_id": item.derived_file_id,
        "derived_file_name": derived_file.name if derived_file else None,
        "derived_file_status": _enum_value(derived_file.status) if derived_file else None,
        "derived_file_classification": _enum_value(derived_file.classification) if derived_file else None,
        "flow_run_id": item.flow_run_id,
        "created_by_agent_id": item.created_by_agent_id,
        "created_by_agent_name": agent_names.get(item.created_by_agent_id),
        "created_at": _iso(item.created_at),
    }


def get_lineage_for_file(db: Session, file_id: str) -> dict:
    file = db.query(File).filter(File.id == file_id).first()
    if not file:
        return {
            "status": "error",
            "message": "file_not_found",
        }

    parents = (
        db.query(FileLineage)
        .filter(FileLineage.derived_file_id == file_id)
        .order_by(FileLineage.created_at.desc())
        .all()
    )

    children = (
        db.query(FileLineage)
        .filter(FileLineage.source_file_id == file_id)
        .order_by(FileLineage.created_at.desc())
        .all()
    )

    related_file_ids = {item.source_file_id for item in parents} | {
        item.derived_file_id for item in children
    }
    related_agent_ids = {item.created_by_agent_id for item in parents + children}

    files_by_id = _file_by_id(db, related_file_ids)
    agent_names = _agent_name_by_id(db, related_agent_ids)

    parent_items = [
        _serialize_parent_item(item, files_by_id, agent_names)
        for item in parents
    ]
    child_items = [
        _serialize_child_item(item, files_by_id, agent_names)
        for item in children
    ]

    return {
        "status": "ok",
        "file": _serialize_file(file),
        "parents": parent_items,
        "children": child_items,
        "summary": {
            "parents_count": len(parent_items),
            "children_count": len(child_items),
            "has_parents": len(parent_items) > 0,
            "has_children": len(child_items) > 0,
        },
    }


def get_lineage_graph(db: Session) -> dict:
    files = db.query(File).order_by(File.created_at.asc()).all()
    lineage = db.query(FileLineage).order_by(FileLineage.created_at.asc()).all()

    agent_ids = {item.created_by_agent_id for item in lineage}
    agent_names = _agent_name_by_id(db, agent_ids)

    nodes = [
        {
            "id": _file_node_id(file.id),
            "raw_id": file.id,
            "label": file.name,
            "type": "file",
            "status": _enum_value(file.status),
            "classification": _enum_value(file.classification),
            "owner_agent_id": file.owner_agent_id,
            "folder_id": file.folder_id,
            "workspace_id": file.workspace_id,
            "created_by_flow_id": file.created_by_flow_id,
            "size": file.size,
            "created_at": _iso(file.created_at),
        }
        for file in files
    ]

    visible_node_ids = {node["id"] for node in nodes}

    edges = []
    for item in lineage:
        source = _file_node_id(item.source_file_id)
        target = _file_node_id(item.derived_file_id)

        if source not in visible_node_ids or target not in visible_node_ids:
            continue

        edges.append(
            {
                "id": f"lineage:{item.id}",
                "source": source,
                "target": target,
                "type": "derived_from",
                "label": "derived",
                "flow_run_id": item.flow_run_id,
                "created_by_agent_id": item.created_by_agent_id,
                "created_by_agent_name": agent_names.get(item.created_by_agent_id),
                "created_at": _iso(item.created_at),
            }
        )

    return {
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "nodes_count": len(nodes),
            "edges_count": len(edges),
            "files": len(files),
            "lineage_edges": len(lineage),
        },
    }