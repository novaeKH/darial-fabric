import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.base import Agent, Team
from app.services.economics_service import (
    as_decimal,
    calculate_llm_cost_breakdown,
    effective_outcome_quantity,
)
from app.models.observability import (
    AIProduct,
    AgentDeployment,
    AgentRun,
    BusinessOutcome,
    Environment,
    LLMCall,
    ModelEndpoint,
    RunStatus,
    TokenSource,
    ToolCall,
)
from app.schemas.observability import (
    AIProductCreate,
    AgentDeploymentCreate,
    BusinessOutcomeCreate,
    LLMCallCreate,
    ModelEndpointCreate,
    RunFinishRequest,
    RunStartRequest,
    ToolCallCreate,
)

MILLION = Decimal("1000000")
SECONDS_PER_HOUR = Decimal("3600")


def _as_decimal(value: int | float | Decimal | None) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def create_product(db: Session, payload: AIProductCreate) -> AIProduct:
    team = db.query(Team).filter(Team.id == payload.owner_team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    existing = (
        db.query(AIProduct)
        .filter(
            AIProduct.owner_team_id == payload.owner_team_id,
            AIProduct.name == payload.name,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="AI product already exists")

    product = AIProduct(**payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


def create_deployment(db: Session, payload: AgentDeploymentCreate) -> AgentDeployment:
    product = db.query(AIProduct).filter(AIProduct.id == payload.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="AI product not found")

    agent = db.query(Agent).filter(Agent.id == payload.agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.team_id != product.owner_team_id:
        raise HTTPException(
            status_code=400,
            detail="Agent and AI product must belong to the same team in the MVP",
        )

    try:
        environment = Environment(payload.environment)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid environment") from exc

    deployment = AgentDeployment(
        product_id=payload.product_id,
        agent_id=payload.agent_id,
        version=payload.version,
        environment=environment,
        cluster=payload.cluster,
        namespace=payload.namespace,
        service_name=payload.service_name,
        framework=payload.framework,
    )
    db.add(deployment)
    db.commit()
    db.refresh(deployment)
    return deployment


def create_model_endpoint(db: Session, payload: ModelEndpointCreate) -> ModelEndpoint:
    endpoint = ModelEndpoint(
        provider=payload.provider,
        model_name=payload.model_name,
        deployment_name=payload.deployment_name,
        hosting_type=payload.hosting_type,
        currency=payload.currency,
        input_price_per_million=_as_decimal(payload.input_price_per_million),
        output_price_per_million=_as_decimal(payload.output_price_per_million),
        cached_input_price_per_million=_as_decimal(
            payload.cached_input_price_per_million
        ),
        reasoning_price_per_million=_as_decimal(payload.reasoning_price_per_million),
        gpu_hour_price=_as_decimal(payload.gpu_hour_price),
    )
    db.add(endpoint)
    db.commit()
    db.refresh(endpoint)
    return endpoint


def start_run(
    db: Session,
    *,
    authenticated_agent_id: str,
    payload: RunStartRequest,
) -> AgentRun:
    agent = db.query(Agent).filter(Agent.id == authenticated_agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    product = db.query(AIProduct).filter(AIProduct.id == payload.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="AI product not found")
    if agent.team_id != product.owner_team_id:
        raise HTTPException(status_code=403, detail="Agent cannot report to this product")

    deployment = None
    if payload.deployment_id:
        deployment = (
            db.query(AgentDeployment)
            .filter(AgentDeployment.id == payload.deployment_id)
            .first()
        )
        if not deployment:
            raise HTTPException(status_code=404, detail="Deployment not found")
        if deployment.agent_id != agent.id or deployment.product_id != product.id:
            raise HTTPException(
                status_code=400,
                detail="Deployment does not match the authenticated agent and product",
            )

    try:
        environment = Environment(payload.environment)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid environment") from exc

    trace_id = payload.trace_id or str(uuid.uuid4())
    existing = db.query(AgentRun).filter(AgentRun.trace_id == trace_id).first()
    if existing:
        return existing

    run = AgentRun(
        trace_id=trace_id,
        product_id=product.id,
        agent_id=agent.id,
        deployment_id=deployment.id if deployment else None,
        workflow_name=payload.workflow_name,
        environment=environment,
        status=RunStatus.running,
        metadata_json=payload.metadata_json,
    )
    db.add(run)

    if deployment:
        deployment.last_seen_at = datetime.utcnow()

    db.commit()
    db.refresh(run)
    return run


def _get_owned_run(db: Session, run_id: str, agent_id: str) -> AgentRun:
    run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.agent_id != agent_id:
        raise HTTPException(status_code=403, detail="Run belongs to another agent")
    return run


def finish_run(
    db: Session,
    *,
    run_id: str,
    authenticated_agent_id: str,
    payload: RunFinishRequest,
) -> AgentRun:
    run = _get_owned_run(db, run_id, authenticated_agent_id)
    try:
        status = RunStatus(payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid run status") from exc

    if status not in {RunStatus.completed, RunStatus.failed, RunStatus.cancelled}:
        raise HTTPException(status_code=400, detail="Run must be finished with a terminal status")

    finished_at = datetime.utcnow()
    run.status = status
    run.finished_at = finished_at
    run.error_type = payload.error_type
    if payload.metadata_json:
        run.metadata_json = {**(run.metadata_json or {}), **payload.metadata_json}
    if run.started_at:
        run.latency_ms = max(
            0,
            int((finished_at - run.started_at).total_seconds() * 1000),
        )

    db.commit()
    db.refresh(run)
    return run


def _resolve_model_endpoint(
    db: Session,
    payload: LLMCallCreate,
) -> ModelEndpoint | None:
    if payload.model_endpoint_id:
        endpoint = (
            db.query(ModelEndpoint)
            .filter(ModelEndpoint.id == payload.model_endpoint_id)
            .first()
        )
        if not endpoint:
            raise HTTPException(status_code=404, detail="Model endpoint not found")
        return endpoint

    return (
        db.query(ModelEndpoint)
        .filter(
            ModelEndpoint.provider == payload.provider,
            ModelEndpoint.model_name == payload.model_name,
            ModelEndpoint.is_active.is_(True),
        )
        .order_by(ModelEndpoint.valid_from.desc())
        .first()
    )


def calculate_llm_cost(payload: LLMCallCreate, endpoint: ModelEndpoint | None) -> Decimal:
    if endpoint is None:
        return Decimal("0")
    return calculate_llm_cost_breakdown(
        input_tokens=payload.input_tokens,
        output_tokens=payload.output_tokens,
        cached_tokens=payload.cached_tokens,
        reasoning_tokens=payload.reasoning_tokens,
        gpu_seconds=payload.gpu_seconds,
        endpoint=endpoint,
    ).total_cost


def record_llm_call(
    db: Session,
    *,
    run_id: str,
    authenticated_agent_id: str,
    payload: LLMCallCreate,
) -> LLMCall:
    run = _get_owned_run(db, run_id, authenticated_agent_id)
    endpoint = _resolve_model_endpoint(db, payload)

    try:
        token_source = TokenSource(payload.token_source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid token source") from exc

    breakdown = (
        calculate_llm_cost_breakdown(
            input_tokens=payload.input_tokens,
            output_tokens=payload.output_tokens,
            cached_tokens=payload.cached_tokens,
            reasoning_tokens=payload.reasoning_tokens,
            gpu_seconds=payload.gpu_seconds,
            endpoint=endpoint,
        )
        if endpoint is not None
        else None
    )
    estimated_cost = breakdown.total_cost if breakdown else Decimal("0")
    metadata_json = dict(payload.metadata_json or {})
    metadata_json["cost_provenance"] = (
        breakdown.as_metadata()
        if breakdown
        else {
            "pricing_method": "not_calculated",
            "reason": "model_endpoint_not_found",
        }
    )
    llm_call = LLMCall(
        run_id=run.id,
        model_endpoint_id=endpoint.id if endpoint else None,
        provider=payload.provider,
        model_name=payload.model_name,
        input_tokens=payload.input_tokens,
        output_tokens=payload.output_tokens,
        cached_tokens=payload.cached_tokens,
        reasoning_tokens=payload.reasoning_tokens,
        gpu_seconds=payload.gpu_seconds,
        latency_ms=payload.latency_ms,
        status=payload.status,
        token_source=token_source,
        estimated_cost=estimated_cost,
        metadata_json=metadata_json,
    )
    db.add(llm_call)
    run.request_count += 1
    run.total_cost = _as_decimal(run.total_cost) + estimated_cost
    db.commit()
    db.refresh(llm_call)
    return llm_call


def record_tool_call(
    db: Session,
    *,
    run_id: str,
    authenticated_agent_id: str,
    payload: ToolCallCreate,
) -> ToolCall:
    run = _get_owned_run(db, run_id, authenticated_agent_id)
    tool_call = ToolCall(
        run_id=run.id,
        tool_name=payload.tool_name,
        status=payload.status,
        latency_ms=payload.latency_ms,
        estimated_cost=_as_decimal(payload.estimated_cost),
        metadata_json={
            **(payload.metadata_json or {}),
            "cost_provenance": {
                "pricing_method": "reported_by_integration",
                "verified": False,
            },
        },
    )
    db.add(tool_call)
    run.total_cost = _as_decimal(run.total_cost) + _as_decimal(payload.estimated_cost)
    db.commit()
    db.refresh(tool_call)
    return tool_call


def record_outcome(
    db: Session,
    *,
    run_id: str,
    authenticated_agent_id: str,
    payload: BusinessOutcomeCreate,
) -> BusinessOutcome:
    run = _get_owned_run(db, run_id, authenticated_agent_id)
    outcome = BusinessOutcome(
        run_id=run.id,
        outcome_type=payload.outcome_type,
        success=payload.success,
        quantity=payload.quantity,
        quality_score=payload.quality_score,
        human_accepted=payload.human_accepted,
        time_saved_minutes=payload.time_saved_minutes,
        estimated_business_value=(
            _as_decimal(payload.estimated_business_value)
            if payload.estimated_business_value is not None
            else None
        ),
        metadata_json=payload.metadata_json,
    )
    db.add(outcome)
    db.commit()
    db.refresh(outcome)
    return outcome


def get_dashboard_summary(
    db: Session,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    product_id: str | None = None,
    agent_id: str | None = None,
) -> dict:
    date_to = date_to or datetime.utcnow()
    date_from = date_from or (date_to - timedelta(days=30))

    run_filters = [
        AgentRun.created_at >= date_from,
        AgentRun.created_at <= date_to,
    ]
    if product_id:
        run_filters.append(AgentRun.product_id == product_id)
    if agent_id:
        run_filters.append(AgentRun.agent_id == agent_id)

    total_runs = db.query(func.count(AgentRun.id)).filter(*run_filters).scalar() or 0
    successful_runs = (
        db.query(func.count(AgentRun.id))
        .filter(*run_filters, AgentRun.status == RunStatus.completed)
        .scalar()
        or 0
    )
    failed_runs = (
        db.query(func.count(AgentRun.id))
        .filter(*run_filters, AgentRun.status == RunStatus.failed)
        .scalar()
        or 0
    )
    total_cost = (
        db.query(func.coalesce(func.sum(AgentRun.total_cost), 0))
        .filter(*run_filters)
        .scalar()
        or Decimal("0")
    )
    failed_run_cost = (
        db.query(func.coalesce(func.sum(AgentRun.total_cost), 0))
        .filter(*run_filters, AgentRun.status == RunStatus.failed)
        .scalar()
        or Decimal("0")
    )
    average_latency_ms = (
        db.query(func.avg(AgentRun.latency_ms))
        .filter(*run_filters, AgentRun.latency_ms.is_not(None))
        .scalar()
    )

    llm_query = db.query(
        func.count(LLMCall.id),
        func.coalesce(func.sum(LLMCall.input_tokens), 0),
        func.coalesce(func.sum(LLMCall.output_tokens), 0),
        func.coalesce(func.sum(LLMCall.cached_tokens), 0),
        func.coalesce(func.sum(LLMCall.reasoning_tokens), 0),
    ).join(AgentRun, LLMCall.run_id == AgentRun.id)
    llm_query = llm_query.filter(*run_filters)
    (
        total_requests,
        input_tokens,
        output_tokens,
        cached_tokens,
        reasoning_tokens,
    ) = llm_query.one()

    period_runs = db.query(AgentRun).filter(*run_filters).all()
    period_run_ids = [run.id for run in period_runs]
    period_outcomes = (
        db.query(BusinessOutcome)
        .filter(BusinessOutcome.run_id.in_(period_run_ids))
        .all()
        if period_run_ids
        else []
    )
    outcomes_by_run: dict[str, list[BusinessOutcome]] = {}
    for outcome in period_outcomes:
        outcomes_by_run.setdefault(outcome.run_id, []).append(outcome)

    successful_outcomes_float = sum(
        effective_outcome_quantity(outcome) for outcome in period_outcomes
    )
    total_business_value = sum(
        float(outcome.estimated_business_value or 0)
        for outcome in period_outcomes
        if effective_outcome_quantity(outcome) > 0
    )
    total_time_saved_minutes = sum(
        float(outcome.time_saved_minutes or 0)
        for outcome in period_outcomes
        if effective_outcome_quantity(outcome) > 0
    )

    rejected_run_cost = 0.0
    for run in period_runs:
        run_outcomes = outcomes_by_run.get(run.id, [])
        if (
            str(getattr(run.status, "value", run.status)).lower()
            in {"completed", "success", "ok"}
            and run_outcomes
            and sum(effective_outcome_quantity(item) for item in run_outcomes) == 0
        ):
            rejected_run_cost += float(run.total_cost or 0)

    total_cost_float = float(total_cost)
    failed_cost_float = float(failed_run_cost)
    waste_cost_float = min(
        total_cost_float,
        failed_cost_float + rejected_run_cost,
    )

    return {
        "period_from": date_from,
        "period_to": date_to,
        "total_runs": int(total_runs),
        "successful_runs": int(successful_runs),
        "failed_runs": int(failed_runs),
        "success_rate": (
            round(successful_runs / total_runs, 4) if total_runs else 0.0
        ),
        "total_requests": int(total_requests or 0),
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "cached_tokens": int(cached_tokens or 0),
        "reasoning_tokens": int(reasoning_tokens or 0),
        # cached_tokens are a subset of input_tokens and reasoning_tokens
        # are a subset of output_tokens; do not count them twice.
        "total_tokens": int((input_tokens or 0) + (output_tokens or 0)),
        "total_cost": round(total_cost_float, 6),
        "failed_run_cost": round(failed_cost_float, 6),
        "rejected_outcome_cost": round(rejected_run_cost, 6),
        "waste_cost": round(waste_cost_float, 6),
        "waste_rate": (
            round(waste_cost_float / total_cost_float, 4)
            if total_cost_float
            else 0.0
        ),
        "successful_outcomes": successful_outcomes_float,
        "time_saved_minutes": round(total_time_saved_minutes, 2),
        "estimated_business_value": round(total_business_value, 6),
        "net_effect": round(total_business_value - total_cost_float, 6),
        "roi": (
            round((total_business_value - total_cost_float) / total_cost_float, 4)
            if total_cost_float
            else None
        ),
        "cost_per_successful_run": (
            round(total_cost_float / successful_runs, 6)
            if successful_runs
            else None
        ),
        "cost_per_outcome": (
            round(total_cost_float / successful_outcomes_float, 6)
            if successful_outcomes_float
            else None
        ),
        "average_latency_ms": (
            round(float(average_latency_ms), 2)
            if average_latency_ms is not None
            else None
        ),
    }
