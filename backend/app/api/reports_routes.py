from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.base import Agent
from app.models.observability import (
    AIProduct,
    AgentRun,
    BusinessOutcome,
    LLMCall,
    PolicyViolation,
)

router = APIRouter(tags=["Management Reports"])


def enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def resolve_period(
    date_from: datetime | None,
    date_to: datetime | None,
) -> tuple[datetime, datetime]:
    end = date_to or datetime.utcnow()
    start = date_from or (end - timedelta(days=30))
    return start, end


def build_report(
    db: Session,
    date_from: datetime | None,
    date_to: datetime | None,
) -> dict[str, Any]:
    start, end = resolve_period(date_from, date_to)

    products = {item.id: item for item in db.query(AIProduct).all()}
    agents = {item.id: item for item in db.query(Agent).all()}

    runs = (
        db.query(AgentRun)
        .filter(
            AgentRun.started_at >= start,
            AgentRun.started_at <= end,
        )
        .all()
    )
    run_ids = [item.id for item in runs]

    llm_calls = (
        db.query(LLMCall)
        .filter(LLMCall.run_id.in_(run_ids))
        .all()
        if run_ids
        else []
    )
    outcomes = (
        db.query(BusinessOutcome)
        .filter(BusinessOutcome.run_id.in_(run_ids))
        .all()
        if run_ids
        else []
    )
    violations = (
        db.query(PolicyViolation)
        .filter(
            PolicyViolation.detected_at >= start,
            PolicyViolation.detected_at <= end,
        )
        .all()
    )

    calls_by_run: dict[str, list[LLMCall]] = defaultdict(list)
    for call in llm_calls:
        calls_by_run[call.run_id].append(call)

    outcomes_by_run: dict[str, list[BusinessOutcome]] = defaultdict(list)
    for outcome in outcomes:
        outcomes_by_run[outcome.run_id].append(outcome)

    product_metrics: dict[str, dict[str, Any]] = {}
    agent_metrics: dict[str, dict[str, Any]] = {}
    daily: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "date": "",
            "runs": 0,
            "successful_runs": 0,
            "cost": 0.0,
            "tokens": 0,
            "outcomes": 0,
        }
    )

    total_cost = 0.0
    total_tokens = 0
    successful_runs = 0
    failed_runs = 0
    successful_outcomes = 0
    total_latency = 0
    latency_count = 0

    for run in runs:
        status = str(enum_value(run.status) or "").lower()
        is_success = status in {"completed", "success", "ok"}
        is_failed = status in {"failed", "cancelled", "error"}

        cost = float(run.total_cost or 0)
        tokens = sum(
            int(call.input_tokens or 0)
            + int(call.output_tokens or 0)
            + int(call.cached_tokens or 0)
            + int(call.reasoning_tokens or 0)
            for call in calls_by_run.get(run.id, [])
        )
        run_outcomes = outcomes_by_run.get(run.id, [])
        run_successful_outcomes = sum(
            1 for item in run_outcomes if bool(item.success)
        )

        total_cost += cost
        total_tokens += tokens
        successful_runs += int(is_success)
        failed_runs += int(is_failed)
        successful_outcomes += run_successful_outcomes

        if run.latency_ms is not None:
            total_latency += int(run.latency_ms)
            latency_count += 1

        product = products.get(run.product_id)
        p = product_metrics.setdefault(
            run.product_id,
            {
                "product_id": run.product_id,
                "product_name": getattr(product, "name", None) or "Unknown product",
                "business_unit": getattr(product, "business_unit", None),
                "runs": 0,
                "successful_runs": 0,
                "failed_runs": 0,
                "cost": 0.0,
                "tokens": 0,
                "outcomes": 0,
                "latency_total": 0,
                "latency_count": 0,
            },
        )
        p["runs"] += 1
        p["successful_runs"] += int(is_success)
        p["failed_runs"] += int(is_failed)
        p["cost"] += cost
        p["tokens"] += tokens
        p["outcomes"] += run_successful_outcomes
        if run.latency_ms is not None:
            p["latency_total"] += int(run.latency_ms)
            p["latency_count"] += 1

        agent = agents.get(run.agent_id)
        a = agent_metrics.setdefault(
            run.agent_id,
            {
                "agent_id": run.agent_id,
                "agent_name": getattr(agent, "name", None) or "Unknown agent",
                "product_id": run.product_id,
                "product_name": getattr(product, "name", None) or "Unknown product",
                "runs": 0,
                "successful_runs": 0,
                "failed_runs": 0,
                "cost": 0.0,
                "tokens": 0,
                "outcomes": 0,
                "latency_total": 0,
                "latency_count": 0,
            },
        )
        a["runs"] += 1
        a["successful_runs"] += int(is_success)
        a["failed_runs"] += int(is_failed)
        a["cost"] += cost
        a["tokens"] += tokens
        a["outcomes"] += run_successful_outcomes
        if run.latency_ms is not None:
            a["latency_total"] += int(run.latency_ms)
            a["latency_count"] += 1

        run_date = run.started_at.date().isoformat()
        d = daily[run_date]
        d["date"] = run_date
        d["runs"] += 1
        d["successful_runs"] += int(is_success)
        d["cost"] += cost
        d["tokens"] += tokens
        d["outcomes"] += run_successful_outcomes

    def enrich(item: dict[str, Any]) -> dict[str, Any]:
        runs_count = item["runs"]
        item["success_rate"] = (
            item["successful_runs"] / runs_count if runs_count else 0.0
        )
        item["cost_per_run"] = (
            item["cost"] / runs_count if runs_count else 0.0
        )
        item["cost_per_outcome"] = (
            item["cost"] / item["outcomes"] if item["outcomes"] else None
        )
        item["average_latency_ms"] = (
            item["latency_total"] / item["latency_count"]
            if item["latency_count"]
            else None
        )
        item.pop("latency_total", None)
        item.pop("latency_count", None)
        return item

    products_rows = [
        enrich(item) for item in product_metrics.values()
    ]
    agents_rows = [
        enrich(item) for item in agent_metrics.values()
    ]

    products_rows.sort(key=lambda item: item["cost"], reverse=True)
    agents_rows.sort(key=lambda item: item["cost"], reverse=True)

    violation_summary = {
        "total": len(violations),
        "critical": sum(
            1 for item in violations
            if str(enum_value(item.severity)).lower() == "critical"
        ),
        "warning": sum(
            1 for item in violations
            if str(enum_value(item.severity)).lower() == "warning"
        ),
        "open": sum(
            1 for item in violations
            if str(enum_value(item.status)).lower() == "open"
        ),
    }

    total_runs = len(runs)
    return {
        "period": {
            "date_from": start,
            "date_to": end,
            "days": max((end.date() - start.date()).days + 1, 1),
        },
        "totals": {
            "runs": total_runs,
            "successful_runs": successful_runs,
            "failed_runs": failed_runs,
            "success_rate": successful_runs / total_runs if total_runs else 0.0,
            "cost": total_cost,
            "tokens": total_tokens,
            "successful_outcomes": successful_outcomes,
            "cost_per_run": total_cost / total_runs if total_runs else 0.0,
            "cost_per_outcome": (
                total_cost / successful_outcomes
                if successful_outcomes
                else None
            ),
            "average_latency_ms": (
                total_latency / latency_count if latency_count else None
            ),
        },
        "violations": violation_summary,
        "products": products_rows,
        "agents": agents_rows,
        "daily": sorted(daily.values(), key=lambda item: item["date"]),
    }


@router.get("/observability/reports/management")
def management_report(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return build_report(db, date_from, date_to)


@router.get("/observability/reports/management.csv")
def management_report_csv(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
):
    report = build_report(db, date_from, date_to)
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    writer.writerow([
        "product_name",
        "business_unit",
        "runs",
        "successful_runs",
        "failed_runs",
        "success_rate",
        "tokens",
        "cost",
        "cost_per_run",
        "outcomes",
        "cost_per_outcome",
        "average_latency_ms",
    ])

    for item in report["products"]:
        writer.writerow([
            item["product_name"],
            item["business_unit"],
            item["runs"],
            item["successful_runs"],
            item["failed_runs"],
            round(item["success_rate"], 6),
            item["tokens"],
            round(item["cost"], 4),
            round(item["cost_per_run"], 4),
            item["outcomes"],
            (
                round(item["cost_per_outcome"], 4)
                if item["cost_per_outcome"] is not None
                else ""
            ),
            (
                round(item["average_latency_ms"], 2)
                if item["average_latency_ms"] is not None
                else ""
            ),
        ])

    buffer.seek(0)
    filename = (
        f"darial-management-report-"
        f"{report['period']['date_from'].date().isoformat()}-"
        f"{report['period']['date_to'].date().isoformat()}.csv"
    )

    return StreamingResponse(
        iter([buffer.getvalue().encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )
