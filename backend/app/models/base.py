import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def uuid_str() -> str:
    return str(uuid.uuid4())


class RiskLevel(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class ClearanceLevel(str, enum.Enum):
    public = "public"
    internal = "internal"
    confidential = "confidential"
    restricted = "restricted"


class FileStatus(str, enum.Enum):
    draft = "draft"
    processed = "processed"
    approved = "approved"
    reviewed = "reviewed"
    quarantined = "quarantined"
    blocked = "blocked"
    archived = "archived"
    expired = "expired"
    deleted = "deleted"


class PermissionAction(str, enum.Enum):
    read = "read"
    write = "write"
    upload = "upload"
    share = "share"
    grant = "grant"
    revoke = "revoke"
    delete = "delete"
    scan = "scan"
    quarantine = "quarantine"
    approve = "approve"


class ResourceType(str, enum.Enum):
    workspace = "workspace"
    folder = "folder"
    file = "file"


class SubjectType(str, enum.Enum):
    user = "user"
    team = "team"
    agent = "agent"


class AuditSeverity(str, enum.Enum):
    info = "info"
    warning = "warning"
    high = "high"
    critical = "critical"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        Index("ix_agents_team_status", "team_id", "status"),
        Index("ix_agents_api_key_hash", "api_key_hash"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)

    team_id: Mapped[str] = mapped_column(String, ForeignKey("teams.id"))
    role: Mapped[str] = mapped_column(String)

    risk_level: Mapped[RiskLevel] = mapped_column(
        Enum(RiskLevel),
        default=RiskLevel.medium,
    )
    autonomy_level: Mapped[int] = mapped_column(Integer, default=2)
    clearance_level: Mapped[ClearanceLevel] = mapped_column(
        Enum(ClearanceLevel),
        default=ClearanceLevel.internal,
    )

    api_key_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    api_key_prefix: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AgentToolPermission(Base):
    __tablename__ = "agent_tool_permissions"
    __table_args__ = (
        Index("ix_agent_tool_permissions_agent_tool", "agent_id", "tool_name"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    agent_id: Mapped[str] = mapped_column(String, ForeignKey("agents.id"))
    tool_name: Mapped[str] = mapped_column(String)
    is_allowed: Mapped[bool] = mapped_column(Boolean, default=True)


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        Index("ix_workspaces_team", "team_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String)

    team_id: Mapped[str] = mapped_column(String, ForeignKey("teams.id"))

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Folder(Base):
    __tablename__ = "folders"
    __table_args__ = (
        Index("ix_folders_workspace_parent", "workspace_id", "parent_folder_id"),
        Index("ix_folders_name", "name"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String)

    workspace_id: Mapped[str] = mapped_column(String, ForeignKey("workspaces.id"))
    parent_folder_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("folders.id"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class File(Base):
    __tablename__ = "files"
    __table_args__ = (
        Index("ix_files_workspace_folder", "workspace_id", "folder_id"),
        Index("ix_files_owner_created", "owner_agent_id", "created_at"),
        Index("ix_files_status", "status"),
        Index("ix_files_classification", "classification"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String)

    workspace_id: Mapped[str] = mapped_column(String, ForeignKey("workspaces.id"))
    folder_id: Mapped[str] = mapped_column(String, ForeignKey("folders.id"))

    object_key: Mapped[str] = mapped_column(String)
    classification: Mapped[ClearanceLevel] = mapped_column(
        Enum(ClearanceLevel),
        default=ClearanceLevel.internal,
    )
    status: Mapped[FileStatus] = mapped_column(
        Enum(FileStatus),
        default=FileStatus.draft,
    )

    owner_agent_id: Mapped[str] = mapped_column(String, ForeignKey("agents.id"))
    created_by_flow_id: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    encrypted_dek: Mapped[str | None] = mapped_column(Text, nullable=True)
    nonce: Mapped[str | None] = mapped_column(String, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    size: Mapped[int] = mapped_column(Integer, default=0)

    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Permission(Base):
    __tablename__ = "permissions"
    __table_args__ = (
        Index("ix_permissions_subject", "subject_type", "subject_id"),
        Index("ix_permissions_resource", "resource_type", "resource_id"),
        Index(
            "ix_permissions_lookup",
            "subject_type",
            "subject_id",
            "resource_type",
            "resource_id",
            "action",
            "status",
        ),
        Index("ix_permissions_expires", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)

    subject_type: Mapped[SubjectType] = mapped_column(Enum(SubjectType))
    subject_id: Mapped[str] = mapped_column(String)

    resource_type: Mapped[ResourceType] = mapped_column(Enum(ResourceType))
    resource_id: Mapped[str] = mapped_column(String)

    action: Mapped[PermissionAction] = mapped_column(Enum(PermissionAction))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    status: Mapped[str] = mapped_column(String, default="active")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_actor_agent", "actor_agent_id", "created_at"),
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
        Index("ix_audit_logs_action", "action"),
        Index("ix_audit_logs_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)

    actor_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    actor_agent_id: Mapped[str | None] = mapped_column(String, nullable=True)

    action: Mapped[str] = mapped_column(String)
    resource_type: Mapped[str | None] = mapped_column(String, nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String, nullable=True)

    status: Mapped[str] = mapped_column(String, default="success")
    severity: Mapped[AuditSeverity] = mapped_column(
        Enum(AuditSeverity),
        default=AuditSeverity.info,
    )

    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SecurityFinding(Base):
    __tablename__ = "security_findings"
    __table_args__ = (
        Index("ix_security_findings_file", "file_id"),
        Index("ix_security_findings_severity", "severity"),
        Index("ix_security_findings_type", "finding_type"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)

    file_id: Mapped[str] = mapped_column(String, ForeignKey("files.id"))

    finding_type: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FileLineage(Base):
    __tablename__ = "file_lineage"
    __table_args__ = (
        Index("ix_file_lineage_source", "source_file_id"),
        Index("ix_file_lineage_derived", "derived_file_id"),
        Index("ix_file_lineage_flow", "flow_run_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)

    source_file_id: Mapped[str] = mapped_column(String, ForeignKey("files.id"))
    derived_file_id: Mapped[str] = mapped_column(String, ForeignKey("files.id"))

    flow_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by_agent_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("agents.id"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FlowRun(Base):
    __tablename__ = "flow_runs"
    __table_args__ = (
        Index("ix_flow_runs_status", "status"),
        Index("ix_flow_runs_started_by", "started_by_agent_id"),
        Index("ix_flow_runs_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)

    name: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="running")

    started_by_agent_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("agents.id"),
        nullable=True,
    )
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# Notes:
# - Relationships are intentionally kept lightweight in the MVP because most
#   services query entities explicitly and the project uses demo reset instead
#   of database migrations.
# - ForeignKey links from files/lineage to flow_runs are intentionally not used
#   for created_by_flow_id and flow_run_id in the MVP to avoid table creation
#   ordering issues during demo reset.
# - Indexes are added for common queries: files by owner/folder/status,
#   permissions by subject/resource, audit by resource/action, security findings
#   by file, lineage by source/derived file, and flow runs by status.