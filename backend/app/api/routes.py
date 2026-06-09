from urllib.parse import quote

from fastapi import APIRouter, Depends, File as FastAPIFile, Form, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import AuthenticatedAgent, require_agent_api_key
from app.core.ws_manager import ws_manager
from app.models.base import (
    Agent,
    AuditLog,
    ClearanceLevel,
    File as ModelFile,
    FlowRun,
    Folder,
    Permission,
    RiskLevel,
    SecurityFinding,
    Team,
    Workspace,
)
from app.schemas.base import (
    AgentCreate,
    AgentRead,
    AgentAuthResponse,
    AuditLogRead,
    FileRead,
    FlowRunRead,
    FolderCreate,
    FolderRead,
    PermissionGrantRequest,
    PermissionRead,
    PolicySimulationRequest,
    ReleaseQuarantineRequest,
    RunFlowRequest,
    ScanFileRequest,
    SecurityFindingRead,
    TeamCreate,
    TeamRead,
    WorkspaceCreate,
    WorkspaceRead,
)
from app.services.compliance_service import generate_compliance_report
from app.services.demo_service import (
    get_demo_checklist,
    get_demo_status,
    reset_demo_database,
    run_clean_demo_scenario,
    run_risk_demo_scenario,
)
from app.services.file_passport_service import get_file_passport
from app.services.file_service import (
    read_file_as_agent,
    read_file_as_authenticated_agent,
    upload_file_as_agent,
)
from app.services.flow_service import run_processing_flow_for_file
from app.services.graph_service import get_access_graph
from app.services.lineage_service import get_lineage_for_file, get_lineage_graph
from app.services.permission_service import grant_permission, revoke_permission
from app.services.policy_engine import simulate_file_access
from app.services.security_scanner import release_from_quarantine, scan_file
from app.services.realtime_service import realtime_connection_count
from app.services.synthetic_agent_service import run_synthetic_generation_once

router = APIRouter()


def _get_team_or_404(db: Session, team_id: str) -> Team:
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


def _get_workspace_or_404(db: Session, workspace_id: str) -> Workspace:
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


def _get_folder_or_404(db: Session, folder_id: str) -> Folder:
    folder = db.query(Folder).filter(Folder.id == folder_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    return folder


def _safe_content_disposition(filename: str) -> str:
    safe_filename = filename.replace("\"", "_").replace("\r", "_").replace("\n", "_")
    encoded_filename = quote(safe_filename)
    return f"attachment; filename=\"{safe_filename}\"; filename*=UTF-8''{encoded_filename}"


def _authenticated_agent_response(agent: AuthenticatedAgent) -> dict:
    return {
        "status": "authenticated",
        "agent": {
            "id": agent.id,
            "name": agent.name,
            "role": agent.role,
            "status": agent.status,
            "api_key_prefix": agent.api_key_prefix,
        },
        "auth_mode": "x_agent_key",
        "message": "Agent identity was derived from X-Agent-Key header.",
    }


@router.get("/health")
def health_check() -> dict:
    return {
        "status": "healthy",
        "service": "secure-workspace-fabric",
    }


@router.get("/ready")
def readiness_check(db: Session = Depends(get_db)) -> dict:
    """
    Production-like readiness check.

    Health means the backend process is alive.
    Readiness means the backend can use its critical dependencies.
    """
    checks = {
        "postgres": "unknown",
        "api": "ok",
        "object_storage": "configured",
        "redis": "configured",
    }

    try:
        db.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = "error"
        return {
            "status": "not_ready",
            "service": "secure-workspace-fabric",
            "checks": checks,
            "error": str(exc),
        }

    return {
        "status": "ready",
        "service": "secure-workspace-fabric",
        "checks": checks,
        "message": "Backend is ready to process requests. PostgreSQL check passed; Redis and object storage are configured by Docker Compose.",
    }

# -------------------------
# Realtime WebSocket
# -------------------------


@router.websocket("/ws/events")
async def realtime_events(websocket: WebSocket):
    """
    Realtime WebSocket channel for frontend live updates.

    Backend sends lightweight events. Frontend receives an event and refreshes
    its state through regular REST endpoints.
    """
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive and allow browser ping/debug messages.
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)



@router.get("/realtime/status")
def realtime_status() -> dict:
    return {
        "status": "ok",
        "service": "secure-workspace-fabric",
        "transport": "websocket",
        "endpoint": "/api/ws/events",
        "active_connections": realtime_connection_count(),
    }


@router.post("/realtime/test")
async def realtime_test() -> dict:
    """
    Manual realtime test event.

    Use this endpoint to verify that the backend can broadcast WebSocket events
    and the frontend can receive them without waiting for demo scenarios.
    """
    await ws_manager.broadcast(
        event_type="realtime_test",
        message="Manual realtime test event",
        payload={
            "workspace_updated": True,
            "source": "manual_test_endpoint",
        },
    )

    return {
        "status": "sent",
        "event_type": "realtime_test",
        "active_connections": realtime_connection_count(),
    }


# -------------------------
# Agent Auth
# -------------------------


@router.get("/auth/agent/me", response_model=AgentAuthResponse)
def authenticated_agent_me(
    current_agent: AuthenticatedAgent = Depends(require_agent_api_key),
):
    """
    Production-like agent authentication check.

    The client sends X-Agent-Key, backend verifies key hash and returns the derived agent identity.
    """
    return _authenticated_agent_response(current_agent)


@router.post("/auth/agent/verify", response_model=AgentAuthResponse)
def verify_authenticated_agent(
    current_agent: AuthenticatedAgent = Depends(require_agent_api_key),
):
    """
    Same as /auth/agent/me, but POST is convenient for Swagger demos.
    """
    return _authenticated_agent_response(current_agent)


# -------------------------
# Teams
# -------------------------


@router.post("/teams", response_model=TeamRead)
def create_team(payload: TeamCreate, db: Session = Depends(get_db)):
    existing = db.query(Team).filter(Team.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Team already exists")

    team = Team(name=payload.name)
    db.add(team)
    db.commit()
    db.refresh(team)
    return team


@router.get("/teams", response_model=list[TeamRead])
def list_teams(db: Session = Depends(get_db)):
    return db.query(Team).order_by(Team.created_at.desc()).all()


# -------------------------
# Agents
# -------------------------


@router.post("/agents", response_model=AgentRead)
def create_agent(payload: AgentCreate, db: Session = Depends(get_db)):
    _get_team_or_404(db, payload.team_id)

    existing = db.query(Agent).filter(Agent.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Agent already exists")

    try:
        risk_level = RiskLevel(payload.risk_level)
        clearance_level = ClearanceLevel(payload.clearance_level)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid risk_level or clearance_level",
        ) from exc

    agent = Agent(
        name=payload.name,
        team_id=payload.team_id,
        role=payload.role,
        risk_level=risk_level,
        autonomy_level=payload.autonomy_level,
        clearance_level=clearance_level,
    )

    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


@router.get("/agents", response_model=list[AgentRead])
def list_agents(db: Session = Depends(get_db)):
    return db.query(Agent).order_by(Agent.created_at.desc()).all()


# -------------------------
# Workspaces
# -------------------------


@router.post("/workspaces", response_model=WorkspaceRead)
def create_workspace(payload: WorkspaceCreate, db: Session = Depends(get_db)):
    _get_team_or_404(db, payload.team_id)

    workspace = Workspace(
        name=payload.name,
        team_id=payload.team_id,
    )

    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return workspace


@router.get("/workspaces", response_model=list[WorkspaceRead])
def list_workspaces(db: Session = Depends(get_db)):
    return db.query(Workspace).order_by(Workspace.created_at.desc()).all()


# -------------------------
# Folders
# -------------------------


@router.post("/folders", response_model=FolderRead)
def create_folder(payload: FolderCreate, db: Session = Depends(get_db)):
    _get_workspace_or_404(db, payload.workspace_id)

    if payload.parent_folder_id:
        parent = _get_folder_or_404(db, payload.parent_folder_id)
        if parent.workspace_id != payload.workspace_id:
            raise HTTPException(
                status_code=400,
                detail="Parent folder belongs to another workspace",
            )

    folder = Folder(
        name=payload.name,
        workspace_id=payload.workspace_id,
        parent_folder_id=payload.parent_folder_id,
    )

    db.add(folder)
    db.commit()
    db.refresh(folder)
    return folder


@router.get("/folders", response_model=list[FolderRead])
def list_folders(
    workspace_id: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(Folder)

    if workspace_id:
        query = query.filter(Folder.workspace_id == workspace_id)

    return query.order_by(Folder.created_at.desc()).all()


# -------------------------
# Files
# -------------------------


@router.post("/files/upload", response_model=FileRead)
def upload_file(
    agent_id: str = Form(...),
    folder_id: str = Form(...),
    classification: str = Form("internal"),
    file: UploadFile = FastAPIFile(...),
    db: Session = Depends(get_db),
):
    return upload_file_as_agent(
        db=db,
        agent_id=agent_id,
        folder_id=folder_id,
        upload=file,
        classification=classification,
    )


@router.get("/files", response_model=list[FileRead])
def list_files(
    folder_id: str | None = None,
    workspace_id: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(ModelFile)

    if folder_id:
        query = query.filter(ModelFile.folder_id == folder_id)

    if workspace_id:
        query = query.filter(ModelFile.workspace_id == workspace_id)

    return query.order_by(ModelFile.created_at.desc()).all()


@router.get("/files/{file_id}/read")
def read_file(
    file_id: str,
    agent_id: str,
    db: Session = Depends(get_db),
):
    file, plain_data = read_file_as_agent(
        db=db,
        agent_id=agent_id,
        file_id=file_id,
    )

    return Response(
        content=plain_data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": _safe_content_disposition(file.name),
        },
    )


@router.get("/files/{file_id}/read-authenticated")
def read_file_authenticated(
    file_id: str,
    current_agent: AuthenticatedAgent = Depends(require_agent_api_key),
    db: Session = Depends(get_db),
):
    """
    Production-like read endpoint.

    The backend derives agent_id from X-Agent-Key and does not trust agent_id from query params.
    This endpoint demonstrates production-like agent authentication while keeping demo-mode endpoints available.
    """
    file, plain_data = read_file_as_authenticated_agent(
        db=db,
        authenticated_agent_id=current_agent.id,
        file_id=file_id,
    )

    return Response(
        content=plain_data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": _safe_content_disposition(file.name),
            "X-Authenticated-Agent": current_agent.name,
        },
    )


# -------------------------
# Audit Logs
# -------------------------


@router.get("/audit", response_model=list[AuditLogRead])
def list_audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return (
        db.query(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .all()
    )


# -------------------------
# Permissions
# -------------------------


@router.post("/permissions/grant", response_model=PermissionRead)
def grant_access(
    payload: PermissionGrantRequest,
    db: Session = Depends(get_db),
):
    return grant_permission(
        db=db,
        subject_agent_id=payload.subject_agent_id,
        resource_type=payload.resource_type,
        resource_id=payload.resource_id,
        action=payload.action,
        expires_in_minutes=payload.expires_in_minutes,
        reason=payload.reason,
        granted_by_agent_id=payload.granted_by_agent_id,
    )


@router.post("/permissions/{permission_id}/revoke", response_model=PermissionRead)
def revoke_access(
    permission_id: str,
    revoked_by_agent_id: str | None = None,
    db: Session = Depends(get_db),
):
    return revoke_permission(
        db=db,
        permission_id=permission_id,
        revoked_by_agent_id=revoked_by_agent_id,
    )


@router.get("/permissions", response_model=list[PermissionRead])
def list_permissions(
    subject_agent_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(Permission)

    if subject_agent_id:
        query = query.filter(Permission.subject_id == subject_agent_id)

    if resource_type:
        query = query.filter(Permission.resource_type == resource_type)

    if resource_id:
        query = query.filter(Permission.resource_id == resource_id)

    return query.order_by(Permission.created_at.desc()).all()


# -------------------------
# Policy Simulator
# -------------------------


@router.post("/policy/simulate")
def simulate_policy(
    payload: PolicySimulationRequest,
    db: Session = Depends(get_db),
):
    return simulate_file_access(
        db=db,
        agent_id=payload.agent_id,
        file_id=payload.file_id,
        action=payload.action,
    )


# -------------------------
# Security Center
# -------------------------


@router.post("/security/scan")
def security_scan_file(
    payload: ScanFileRequest,
    db: Session = Depends(get_db),
):
    return scan_file(
        db=db,
        file_id=payload.file_id,
        scanner_agent_id=payload.scanner_agent_id,
    )


@router.get("/security/findings", response_model=list[SecurityFindingRead])
def list_security_findings(
    file_id: str | None = None,
    severity: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(SecurityFinding)

    if file_id:
        query = query.filter(SecurityFinding.file_id == file_id)

    if severity:
        query = query.filter(SecurityFinding.severity == severity)

    return query.order_by(SecurityFinding.created_at.desc()).all()


@router.post("/security/release", response_model=FileRead)
def release_file_from_quarantine(
    payload: ReleaseQuarantineRequest,
    db: Session = Depends(get_db),
):
    try:
        return release_from_quarantine(
            db=db,
            file_id=payload.file_id,
            released_by_agent_id=payload.released_by_agent_id,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc


# -------------------------
# Synthetic Data Agent
# -------------------------


@router.post("/synthetic/run-once")
def run_synthetic_agent_once(
    db: Session = Depends(get_db),
):
    return run_synthetic_generation_once(db)


# -------------------------
# Flow Engine
# -------------------------


@router.post("/flows/run-processing-flow")
def run_processing_flow(
    payload: RunFlowRequest,
    db: Session = Depends(get_db),
):
    return run_processing_flow_for_file(
        db=db,
        source_file_id=payload.source_file_id,
    )


@router.get("/flows", response_model=list[FlowRunRead])
def list_flow_runs(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return (
        db.query(FlowRun)
        .order_by(FlowRun.created_at.desc())
        .limit(limit)
        .all()
    )


# -------------------------
# Lineage
# -------------------------


@router.get("/files/{file_id}/lineage")
def file_lineage(
    file_id: str,
    db: Session = Depends(get_db),
):
    return get_lineage_for_file(
        db=db,
        file_id=file_id,
    )


@router.get("/graph/lineage")
def lineage_graph(
    db: Session = Depends(get_db),
):
    return get_lineage_graph(db)


# -------------------------
# File Passport
# -------------------------


@router.get("/files/{file_id}/passport")
def file_passport(
    file_id: str,
    db: Session = Depends(get_db),
):
    return get_file_passport(
        db=db,
        file_id=file_id,
    )


# -------------------------
# Graph
# -------------------------


@router.get("/graph/access")
def access_graph(
    db: Session = Depends(get_db),
):
    return get_access_graph(db)


# -------------------------
# Compliance
# -------------------------


@router.get("/reports/compliance")
def compliance_report(
    db: Session = Depends(get_db),
):
    return generate_compliance_report(db)


# -------------------------
# Demo
# -------------------------


@router.post("/demo/reset")
def demo_reset():
    return reset_demo_database()


@router.post("/demo/run-clean-scenario")
def demo_run_clean_scenario(
    db: Session = Depends(get_db),
):
    return run_clean_demo_scenario(db)


@router.post("/demo/run-risk-scenario")
def demo_run_risk_scenario(
    db: Session = Depends(get_db),
):
    return run_risk_demo_scenario(db)


@router.get("/demo/status")
def demo_status(
    db: Session = Depends(get_db),
):
    return get_demo_status(db)


@router.get("/demo/checklist")
def demo_checklist(
    db: Session = Depends(get_db),
):
    return get_demo_checklist(db)