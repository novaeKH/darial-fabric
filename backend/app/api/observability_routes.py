from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.auth import AuthenticatedAgent, require_agent_api_key
from app.core.database import get_db
from app.models.observability import AIProduct, AgentDeployment, AgentRun, LLMCall, ModelEndpoint
from app.schemas.observability import (
    AIProductCreate,
    AIProductRead,
    AgentDeploymentCreate,
    AgentDeploymentRead,
    AgentRunRead,
    BusinessOutcomeCreate,
    BusinessOutcomeRead,
    DashboardSummary,
    LLMCallCreate,
    LLMCallRead,
    ModelEndpointCreate,
    ModelEndpointRead,
    RunFinishRequest,
    RunStartRequest,
    ToolCallCreate,
    ToolCallRead,
)
from app.services.observability_service import (
    create_deployment,
    create_model_endpoint,
    create_product,
    finish_run,
    get_dashboard_summary,
    record_llm_call,
    record_outcome,
    record_tool_call,
    start_run,
)
from fastapi import Request
from app.security.product_scope import ensure_product_access, get_request_product_scope

router = APIRouter(tags=["AI Observability"])


@router.post("/ai-products", response_model=AIProductRead)
def register_ai_product(
    payload: AIProductCreate,
    db: Session = Depends(get_db),
):
    return create_product(db, payload)


@router.get("/ai-products", response_model=list[AIProductRead])
def list_ai_products(
    request: Request,
    team_id: str | None = None,
    db: Session = Depends(get_db),
):
    scope = get_request_product_scope(request, db)
    query = db.query(AIProduct)

    if not scope.organization_wide:
        query = query.filter(AIProduct.id.in_(scope.product_ids))

    if team_id:
        query = query.filter(AIProduct.owner_team_id == team_id)

    return query.order_by(AIProduct.created_at.desc()).all()


@router.post("/agent-deployments", response_model=AgentDeploymentRead)
def register_agent_deployment(
    payload: AgentDeploymentCreate,
    db: Session = Depends(get_db),
):
    return create_deployment(db, payload)


@router.get("/agent-deployments", response_model=list[AgentDeploymentRead])
def list_agent_deployments(
    request: Request,
    product_id: str | None = None,
    agent_id: str | None = None,
    environment: str | None = None,
    db: Session = Depends(get_db),
):
    scope = get_request_product_scope(request, db)

    if product_id:
        ensure_product_access(scope, product_id)

    query = db.query(AgentDeployment)

    if not scope.organization_wide:
        query = query.filter(AgentDeployment.product_id.in_(scope.product_ids))

    if product_id:
        query = query.filter(AgentDeployment.product_id == product_id)
    if agent_id:
        query = query.filter(AgentDeployment.agent_id == agent_id)
    if environment:
        query = query.filter(AgentDeployment.environment == environment)

    return query.order_by(AgentDeployment.deployed_at.desc()).all()


@router.post("/model-endpoints", response_model=ModelEndpointRead)
def register_model_endpoint(
    payload: ModelEndpointCreate,
    db: Session = Depends(get_db),
):
    return create_model_endpoint(db, payload)


@router.get("/model-endpoints", response_model=list[ModelEndpointRead])
def list_model_endpoints(
    active_only: bool = True,
    db: Session = Depends(get_db),
):
    query = db.query(ModelEndpoint)
    if active_only:
        query = query.filter(ModelEndpoint.is_active.is_(True))
    return query.order_by(ModelEndpoint.created_at.desc()).all()


@router.post("/telemetry/runs/start", response_model=AgentRunRead)
def telemetry_start_run(
    payload: RunStartRequest,
    current_agent: AuthenticatedAgent = Depends(require_agent_api_key),
    db: Session = Depends(get_db),
):
    return start_run(
        db,
        authenticated_agent_id=current_agent.id,
        payload=payload,
    )


@router.patch("/telemetry/runs/{run_id}/finish", response_model=AgentRunRead)
def telemetry_finish_run(
    run_id: str,
    payload: RunFinishRequest,
    current_agent: AuthenticatedAgent = Depends(require_agent_api_key),
    db: Session = Depends(get_db),
):
    return finish_run(
        db,
        run_id=run_id,
        authenticated_agent_id=current_agent.id,
        payload=payload,
    )


@router.post("/telemetry/runs/{run_id}/llm-calls", response_model=LLMCallRead)
def telemetry_record_llm_call(
    run_id: str,
    payload: LLMCallCreate,
    current_agent: AuthenticatedAgent = Depends(require_agent_api_key),
    db: Session = Depends(get_db),
):
    return record_llm_call(
        db,
        run_id=run_id,
        authenticated_agent_id=current_agent.id,
        payload=payload,
    )


@router.post("/telemetry/runs/{run_id}/tool-calls", response_model=ToolCallRead)
def telemetry_record_tool_call(
    run_id: str,
    payload: ToolCallCreate,
    current_agent: AuthenticatedAgent = Depends(require_agent_api_key),
    db: Session = Depends(get_db),
):
    return record_tool_call(
        db,
        run_id=run_id,
        authenticated_agent_id=current_agent.id,
        payload=payload,
    )


@router.post("/telemetry/runs/{run_id}/outcomes", response_model=BusinessOutcomeRead)
def telemetry_record_outcome(
    run_id: str,
    payload: BusinessOutcomeCreate,
    current_agent: AuthenticatedAgent = Depends(require_agent_api_key),
    db: Session = Depends(get_db),
):
    return record_outcome(
        db,
        run_id=run_id,
        authenticated_agent_id=current_agent.id,
        payload=payload,
    )


@router.get("/observability/runs", response_model=list[AgentRunRead])
def list_agent_runs(
    request: Request,
    product_id: str | None = None,
    agent_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    scope = get_request_product_scope(request, db)

    if product_id:
        ensure_product_access(scope, product_id)

    token_totals = (
        db.query(
            LLMCall.run_id.label("run_id"),
            func.coalesce(func.sum(LLMCall.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(LLMCall.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(LLMCall.cached_tokens), 0).label("cached_tokens"),
            func.coalesce(func.sum(LLMCall.reasoning_tokens), 0).label("reasoning_tokens"),
        )
        .group_by(LLMCall.run_id)
        .subquery()
    )

    query = (
        db.query(
            AgentRun,
            func.coalesce(token_totals.c.input_tokens, 0).label("input_tokens"),
            func.coalesce(token_totals.c.output_tokens, 0).label("output_tokens"),
            func.coalesce(token_totals.c.cached_tokens, 0).label("cached_tokens"),
            func.coalesce(token_totals.c.reasoning_tokens, 0).label("reasoning_tokens"),
        )
        .outerjoin(token_totals, token_totals.c.run_id == AgentRun.id)
    )

    if not scope.organization_wide:
        query = query.filter(AgentRun.product_id.in_(scope.product_ids))

    if product_id:
        query = query.filter(AgentRun.product_id == product_id)
    if agent_id:
        query = query.filter(AgentRun.agent_id == agent_id)
    if status:
        query = query.filter(AgentRun.status == status)

    rows = query.order_by(AgentRun.created_at.desc()).limit(limit).all()
    result: list[AgentRunRead] = []

    for run, input_tokens, output_tokens, cached_tokens, reasoning_tokens in rows:
        # cached_tokens are a subset of input_tokens; reasoning_tokens are a
        # subset of output_tokens, so total_tokens must not count them twice.
        run_data = AgentRunRead.model_validate(run).model_dump()
        run_data.update(
            {
                "input_tokens": int(input_tokens or 0),
                "output_tokens": int(output_tokens or 0),
                "cached_tokens": int(cached_tokens or 0),
                "reasoning_tokens": int(reasoning_tokens or 0),
                "total_tokens": int(
                    (input_tokens or 0) + (output_tokens or 0)
                ),
            }
        )
        result.append(AgentRunRead(**run_data))

    return result


@router.get("/observability/dashboard/summary", response_model=DashboardSummary)
def observability_dashboard_summary(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    product_id: str | None = None,
    agent_id: str | None = None,
    db: Session = Depends(get_db),
):
    return get_dashboard_summary(
        db,
        date_from=date_from,
        date_to=date_to,
        product_id=product_id,
        agent_id=agent_id,
    )
