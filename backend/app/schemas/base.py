from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TeamCreate(BaseModel):
    name: str


class TeamRead(BaseModel):
    id: str
    name: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentCreate(BaseModel):
    name: str
    team_id: str
    role: str
    risk_level: str = "medium"
    autonomy_level: int = Field(default=2, ge=0, le=5)
    clearance_level: str = "internal"


class AgentRead(BaseModel):
    id: str
    name: str
    team_id: str
    role: str
    risk_level: str
    autonomy_level: int
    clearance_level: str
    status: str
    api_key_prefix: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# New schemas for authenticated agent and auth response
class AuthenticatedAgentRead(BaseModel):
    id: str
    name: str
    role: str | None = None
    status: str | None = None
    api_key_prefix: str | None = None


class AgentAuthResponse(BaseModel):
    status: str
    agent: AuthenticatedAgentRead
    auth_mode: str
    message: str


class WorkspaceCreate(BaseModel):
    name: str
    team_id: str


class WorkspaceRead(BaseModel):
    id: str
    name: str
    team_id: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FolderCreate(BaseModel):
    name: str
    workspace_id: str
    parent_folder_id: str | None = None


class FolderRead(BaseModel):
    id: str
    name: str
    workspace_id: str
    parent_folder_id: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FileRead(BaseModel):
    id: str
    name: str
    display_name: str | None = None
    display_type: str | None = None
    description: str | None = None
    original_filename: str | None = None
    workspace_id: str
    folder_id: str
    object_key: str
    classification: str
    status: str
    owner_agent_id: str
    content_hash: str | None
    size: int
    metadata_json: dict[str, Any] | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditLogRead(BaseModel):
    id: str
    actor_user_id: str | None
    actor_agent_id: str | None
    action: str
    resource_type: str | None
    resource_id: str | None
    status: str
    severity: str
    reason: str | None
    details: dict[str, Any] | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PermissionGrantRequest(BaseModel):
    subject_agent_id: str
    resource_type: str
    resource_id: str
    action: str
    expires_in_minutes: int | None = Field(default=None, ge=1)
    reason: str | None = None
    granted_by_agent_id: str | None = None


class PermissionRead(BaseModel):
    id: str
    subject_type: str
    subject_id: str
    resource_type: str
    resource_id: str
    action: str
    expires_at: datetime | None
    status: str
    reason: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PolicySimulationRequest(BaseModel):
    agent_id: str
    file_id: str
    action: str = "read"


class SecurityFindingRead(BaseModel):
    id: str
    file_id: str
    finding_type: str
    severity: str
    description: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ScanFileRequest(BaseModel):
    file_id: str
    scanner_agent_id: str | None = None


class ReleaseQuarantineRequest(BaseModel):
    file_id: str
    released_by_agent_id: str | None = None
    reason: str | None = None


class RunFlowRequest(BaseModel):
    source_file_id: str


class FlowRunRead(BaseModel):
    id: str
    name: str
    status: str
    started_by_agent_id: str | None
    details: dict[str, Any] | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Notes:
# - This file contains API schemas, not SQLAlchemy database models.
# - Database tables and indexes are defined in backend/app/models/base.py.
# - Keep schemas lightweight: validation here should protect request payloads,
#   while business rules stay in services and policy_engine.py.