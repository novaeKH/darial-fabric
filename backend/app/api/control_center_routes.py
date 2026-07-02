from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.base import Agent
from app.models.observability import (
    AIProduct,
    AgentDeployment,
    AgentRun,
    BusinessOutcome,
    LLMCall,
    PolicyViolation,
    ToolCall,
)

router = APIRouter(tags=["AI Control Center"])


def enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


@router.get("/observability/agents/summary")
def get_agents_summary(db: Session = Depends(get_db)):
    products = {item.id: item for item in db.query(AIProduct).all()}
    agents = {item.id: item for item in db.query(Agent).all()}
    deployments = db.query(AgentDeployment).all()
    runs = db.query(AgentRun).all()
    llm_calls = db.query(LLMCall).all()

    calls_by_run: dict[str, list[LLMCall]] = defaultdict(list)
    for call in llm_calls:
        calls_by_run[call.run_id].append(call)

    runs_by_deployment: dict[str, list[AgentRun]] = defaultdict(list)
    runs_by_agent: dict[str, list[AgentRun]] = defaultdict(list)
    for run in runs:
        if run.deployment_id:
            runs_by_deployment[run.deployment_id].append(run)
        runs_by_agent[run.agent_id].append(run)

    result = []
    for deployment in deployments:
        agent = agents.get(deployment.agent_id)
        product = products.get(deployment.product_id)
        agent_runs = runs_by_deployment.get(deployment.id) or runs_by_agent.get(deployment.agent_id, [])

        input_tokens = 0
        output_tokens = 0
        cached_tokens = 0
        reasoning_tokens = 0
        llm_requests = 0
        model_names: set[str] = set()

        for run in agent_runs:
            for call in calls_by_run.get(run.id, []):
                input_tokens += int(call.input_tokens or 0)
                output_tokens += int(call.output_tokens or 0)
                cached_tokens += int(call.cached_tokens or 0)
                reasoning_tokens += int(call.reasoning_tokens or 0)
                llm_requests += 1
                if call.model_name:
                    model_names.add(call.model_name)

        successful_runs = sum(
            1 for run in agent_runs if enum_value(run.status) in {"completed", "success", "ok"}
        )
        failed_runs = sum(
            1 for run in agent_runs if enum_value(run.status) in {"failed", "cancelled", "error"}
        )
        total_cost = sum(float(run.total_cost or 0) for run in agent_runs)
        latencies = [run.latency_ms for run in agent_runs if run.latency_ms is not None]
        last_activity = max(
            (
                run.finished_at or run.started_at or run.created_at
                for run in agent_runs
                if run.finished_at or run.started_at or run.created_at
            ),
            default=deployment.last_seen_at,
        )

        total_runs = len(agent_runs)
        total_tokens = input_tokens + output_tokens + cached_tokens + reasoning_tokens

        result.append(
            {
                "deployment_id": deployment.id,
                "agent_id": deployment.agent_id,
                "agent_name": getattr(agent, "name", None) or deployment.service_name or deployment.agent_id,
                "agent_status": getattr(agent, "status", None),
                "product_id": deployment.product_id,
                "product_name": getattr(product, "name", None),
                "environment": enum_value(deployment.environment),
                "version": deployment.version,
                "cluster": deployment.cluster,
                "namespace": deployment.namespace,
                "service_name": deployment.service_name,
                "framework": deployment.framework,
                "deployment_status": deployment.status,
                "total_runs": total_runs,
                "successful_runs": successful_runs,
                "failed_runs": failed_runs,
                "success_rate": successful_runs / total_runs if total_runs else 0.0,
                "llm_requests": llm_requests,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cached_tokens": cached_tokens,
                "reasoning_tokens": reasoning_tokens,
                "total_tokens": total_tokens,
                "total_cost": total_cost,
                "average_latency_ms": (
                    sum(latencies) / len(latencies) if latencies else None
                ),
                "last_activity_at": last_activity,
                "models": sorted(model_names),
            }
        )

    return sorted(result, key=lambda item: item["total_cost"], reverse=True)


@router.get("/observability/runs/{run_id}/details")
def get_run_details(run_id: str, db: Session = Depends(get_db)):
    run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    product = db.query(AIProduct).filter(AIProduct.id == run.product_id).first()
    agent = db.query(Agent).filter(Agent.id == run.agent_id).first()
    deployment = None
    if run.deployment_id:
        deployment = (
            db.query(AgentDeployment)
            .filter(AgentDeployment.id == run.deployment_id)
            .first()
        )

    llm_calls = db.query(LLMCall).filter(LLMCall.run_id == run.id).order_by(LLMCall.created_at).all()
    tool_calls = db.query(ToolCall).filter(ToolCall.run_id == run.id).order_by(ToolCall.created_at).all()
    outcomes = db.query(BusinessOutcome).filter(BusinessOutcome.run_id == run.id).order_by(BusinessOutcome.created_at).all()
    violations = db.query(PolicyViolation).filter(PolicyViolation.run_id == run.id).order_by(PolicyViolation.detected_at).all()

    def serialize_llm(item: LLMCall):
        return {
            "id": item.id,
            "provider": item.provider,
            "model_name": item.model_name,
            "input_tokens": item.input_tokens,
            "output_tokens": item.output_tokens,
            "cached_tokens": item.cached_tokens,
            "reasoning_tokens": item.reasoning_tokens,
            "total_tokens": (
                int(item.input_tokens or 0)
                + int(item.output_tokens or 0)
                + int(item.cached_tokens or 0)
                + int(item.reasoning_tokens or 0)
            ),
            "gpu_seconds": item.gpu_seconds,
            "latency_ms": item.latency_ms,
            "status": item.status,
            "token_source": enum_value(item.token_source),
            "estimated_cost": float(item.estimated_cost or 0),
            "created_at": item.created_at,
        }

    return {
        "run": {
            "id": run.id,
            "trace_id": run.trace_id,
            "workflow_name": run.workflow_name,
            "environment": enum_value(run.environment),
            "status": enum_value(run.status),
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "latency_ms": run.latency_ms,
            "request_count": run.request_count,
            "total_cost": float(run.total_cost or 0),
            "error_type": run.error_type,
            "metadata_json": run.metadata_json,
        },
        "product": {
            "id": product.id,
            "name": product.name,
        } if product else None,
        "agent": {
            "id": agent.id,
            "name": agent.name,
            "status": agent.status,
        } if agent else None,
        "deployment": {
            "id": deployment.id,
            "version": deployment.version,
            "environment": enum_value(deployment.environment),
            "cluster": deployment.cluster,
            "namespace": deployment.namespace,
            "service_name": deployment.service_name,
            "framework": deployment.framework,
        } if deployment else None,
        "llm_calls": [serialize_llm(item) for item in llm_calls],
        "tool_calls": [
            {
                "id": item.id,
                "tool_name": item.tool_name,
                "status": item.status,
                "latency_ms": item.latency_ms,
                "estimated_cost": float(item.estimated_cost or 0),
                "created_at": item.created_at,
            }
            for item in tool_calls
        ],
        "outcomes": [
            {
                "id": item.id,
                "outcome_type": item.outcome_type,
                "success": item.success,
                "quantity": item.quantity,
                "quality_score": item.quality_score,
                "human_accepted": item.human_accepted,
                "time_saved_minutes": item.time_saved_minutes,
                "estimated_business_value": (
                    float(item.estimated_business_value)
                    if item.estimated_business_value is not None
                    else None
                ),
                "created_at": item.created_at,
            }
            for item in outcomes
        ],
        "violations": [
            {
                "id": item.id,
                "policy_code": item.policy_code,
                "severity": item.severity,
                "description": item.description,
                "status": enum_value(item.status),
                "detected_at": item.detected_at,
            }
            for item in violations
        ],
    }
