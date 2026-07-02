from __future__ import annotations

from calendar import monthrange
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.observability import (
    AIProduct,
    AgentRun,
    Budget,
    BudgetPeriod,
    BudgetScopeType,
    PolicyViolation,
    ViolationStatus,
)

router = APIRouter(tags=["AI FinOps"])


def value_of(value: Any) -> Any:
    return getattr(value, "value", value)


class ProductBudgetPayload(BaseModel):
    limit_amount: float = Field(gt=0)
    warning_threshold: float = Field(default=0.8, ge=0.1, le=1.0)
    currency: str = Field(default="RUB", min_length=3, max_length=8)


def month_bounds(now: datetime) -> tuple[datetime, datetime, int, int]:
    start = datetime(now.year, now.month, 1)
    days_in_month = monthrange(now.year, now.month)[1]
    end = datetime(now.year, now.month, days_in_month, 23, 59, 59, 999999)
    elapsed_days = max(now.day, 1)
    return start, end, days_in_month, elapsed_days


def calculate_product_costs(db: Session, now: datetime) -> dict[str, dict[str, float]]:
    start, end, days_in_month, elapsed_days = month_bounds(now)
    runs = (
        db.query(AgentRun)
        .filter(AgentRun.started_at >= start, AgentRun.started_at <= end)
        .all()
    )

    result: dict[str, dict[str, float]] = {}
    for run in runs:
        current = result.setdefault(
            run.product_id,
            {"actual": 0.0, "runs": 0.0, "failed_cost": 0.0},
        )
        cost = float(run.total_cost or 0)
        current["actual"] += cost
        current["runs"] += 1
        if value_of(run.status) in {"failed", "cancelled", "error"}:
            current["failed_cost"] += cost

    for current in result.values():
        daily_average = current["actual"] / elapsed_days
        current["forecast"] = daily_average * days_in_month
        current["days_in_month"] = float(days_in_month)
        current["elapsed_days"] = float(elapsed_days)

    return result


def budget_status(actual: float, forecast: float, limit_amount: float, warning: float) -> str:
    if actual >= limit_amount or forecast >= limit_amount:
        return "critical"
    if actual >= limit_amount * warning or forecast >= limit_amount * warning:
        return "warning"
    return "healthy"


@router.get("/observability/budgets/summary")
def budgets_summary(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    start, end, days_in_month, elapsed_days = month_bounds(now)
    products = {item.id: item for item in db.query(AIProduct).all()}
    budgets = (
        db.query(Budget)
        .filter(
            Budget.scope_type == BudgetScopeType.product,
            Budget.period == BudgetPeriod.monthly,
            Budget.is_active.is_(True),
        )
        .all()
    )
    budget_by_product = {item.scope_id: item for item in budgets}
    costs = calculate_product_costs(db, now)

    rows = []
    total_limit = 0.0
    total_actual = 0.0
    total_forecast = 0.0

    for product_id, product in products.items():
        budget = budget_by_product.get(product_id)
        metrics = costs.get(
            product_id,
            {
                "actual": 0.0,
                "forecast": 0.0,
                "runs": 0.0,
                "failed_cost": 0.0,
            },
        )
        limit_amount = float(budget.limit_amount) if budget else 0.0
        warning_threshold = float(budget.warning_threshold) if budget else 0.8
        actual = float(metrics["actual"])
        forecast = float(metrics.get("forecast", 0))
        utilization = actual / limit_amount if limit_amount else 0.0
        forecast_utilization = forecast / limit_amount if limit_amount else 0.0
        status = (
            budget_status(actual, forecast, limit_amount, warning_threshold)
            if budget
            else "unconfigured"
        )

        rows.append(
            {
                "product_id": product_id,
                "product_name": product.name,
                "business_unit": product.business_unit,
                "budget_id": budget.id if budget else None,
                "limit_amount": limit_amount,
                "warning_threshold": warning_threshold,
                "currency": budget.currency if budget else "RUB",
                "actual_cost": actual,
                "forecast_cost": forecast,
                "utilization": utilization,
                "forecast_utilization": forecast_utilization,
                "runs": int(metrics["runs"]),
                "failed_cost": float(metrics["failed_cost"]),
                "status": status,
            }
        )
        total_limit += limit_amount
        total_actual += actual
        total_forecast += forecast

    counts = {
        "healthy": sum(1 for item in rows if item["status"] == "healthy"),
        "warning": sum(1 for item in rows if item["status"] == "warning"),
        "critical": sum(1 for item in rows if item["status"] == "critical"),
        "unconfigured": sum(1 for item in rows if item["status"] == "unconfigured"),
    }

    return {
        "period": {
            "type": "monthly",
            "start": start,
            "end": end,
            "days_in_month": days_in_month,
            "elapsed_days": elapsed_days,
        },
        "totals": {
            "limit_amount": total_limit,
            "actual_cost": total_actual,
            "forecast_cost": total_forecast,
            "utilization": total_actual / total_limit if total_limit else 0.0,
            "forecast_utilization": total_forecast / total_limit if total_limit else 0.0,
        },
        "counts": counts,
        "products": sorted(rows, key=lambda item: item["forecast_utilization"], reverse=True),
    }


@router.put("/budgets/products/{product_id}")
def upsert_product_budget(
    product_id: str,
    payload: ProductBudgetPayload,
    db: Session = Depends(get_db),
):
    product = db.query(AIProduct).filter(AIProduct.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="AI product not found")

    budget = (
        db.query(Budget)
        .filter(
            Budget.scope_type == BudgetScopeType.product,
            Budget.scope_id == product_id,
            Budget.period == BudgetPeriod.monthly,
            Budget.is_active.is_(True),
        )
        .first()
    )

    if not budget:
        budget = Budget(
            scope_type=BudgetScopeType.product,
            scope_id=product_id,
            period=BudgetPeriod.monthly,
            limit_amount=Decimal(str(payload.limit_amount)),
            warning_threshold=payload.warning_threshold,
            currency=payload.currency.upper(),
            is_active=True,
        )
        db.add(budget)
    else:
        budget.limit_amount = Decimal(str(payload.limit_amount))
        budget.warning_threshold = payload.warning_threshold
        budget.currency = payload.currency.upper()

    db.commit()
    db.refresh(budget)
    return {
        "id": budget.id,
        "product_id": product_id,
        "limit_amount": float(budget.limit_amount),
        "warning_threshold": budget.warning_threshold,
        "currency": budget.currency,
    }


@router.post("/observability/budgets/recalculate-alerts")
def recalculate_budget_alerts(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    products = {item.id: item for item in db.query(AIProduct).all()}
    budgets = (
        db.query(Budget)
        .filter(
            Budget.scope_type == BudgetScopeType.product,
            Budget.period == BudgetPeriod.monthly,
            Budget.is_active.is_(True),
        )
        .all()
    )
    costs = calculate_product_costs(db, now)

    managed_codes = {"BUDGET_WARNING", "BUDGET_FORECAST_EXCEEDED", "BUDGET_EXCEEDED"}
    existing = (
        db.query(PolicyViolation)
        .filter(
            PolicyViolation.policy_code.in_(managed_codes),
            PolicyViolation.status == ViolationStatus.open,
        )
        .all()
    )
    for item in existing:
        item.status = ViolationStatus.resolved
        item.resolved_at = now

    created = []
    for budget in budgets:
        metrics = costs.get(budget.scope_id, {"actual": 0.0, "forecast": 0.0})
        actual = float(metrics["actual"])
        forecast = float(metrics.get("forecast", 0))
        limit_amount = float(budget.limit_amount)
        warning_amount = limit_amount * float(budget.warning_threshold)
        product = products.get(budget.scope_id)

        code = None
        severity = None
        description = None

        if actual >= limit_amount:
            code = "BUDGET_EXCEEDED"
            severity = "critical"
            description = (
                f"Фактические расходы {actual:.2f} {budget.currency} превысили "
                f"бюджет {limit_amount:.2f} {budget.currency}."
            )
        elif forecast >= limit_amount:
            code = "BUDGET_FORECAST_EXCEEDED"
            severity = "critical"
            description = (
                f"Прогноз {forecast:.2f} {budget.currency} превышает "
                f"месячный бюджет {limit_amount:.2f} {budget.currency}."
            )
        elif actual >= warning_amount or forecast >= warning_amount:
            code = "BUDGET_WARNING"
            severity = "warning"
            description = (
                f"Расходы или прогноз достигли порога "
                f"{float(budget.warning_threshold) * 100:.0f}% бюджета."
            )

        if code:
            item = PolicyViolation(
                product_id=budget.scope_id,
                policy_code=code,
                severity=severity,
                description=description,
                status=ViolationStatus.open,
                details={
                    "product_name": getattr(product, "name", None),
                    "actual_cost": actual,
                    "forecast_cost": forecast,
                    "limit_amount": limit_amount,
                    "warning_threshold": budget.warning_threshold,
                    "currency": budget.currency,
                },
                detected_at=now,
            )
            db.add(item)
            created.append(
                {
                    "product_id": budget.scope_id,
                    "product_name": getattr(product, "name", None),
                    "policy_code": code,
                    "severity": severity,
                }
            )

    db.commit()
    return {"created": len(created), "alerts": created}
