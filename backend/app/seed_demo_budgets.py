from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.observability import (
    AIProduct,
    AgentRun,
    Budget,
    BudgetPeriod,
    BudgetScopeType,
)


def main() -> None:
    now = datetime.utcnow()
    since = now - timedelta(days=30)

    with SessionLocal() as db:
        products = list(db.scalars(select(AIProduct)).all())
        runs = list(
            db.scalars(
                select(AgentRun).where(AgentRun.started_at >= since)
            ).all()
        )

        costs = {product.id: Decimal("0") for product in products}
        for run in runs:
            costs[run.product_id] = costs.get(run.product_id, Decimal("0")) + Decimal(
                str(run.total_cost or 0)
            )

        for product in products:
            recent_cost = costs.get(product.id, Decimal("0"))
            # Бюджет чуть выше последних 30 дней: полезно для демонстрации
            # предупреждений и прогноза, но не создаёт искусственное превышение факта.
            limit_amount = max(
                (recent_cost * Decimal("1.08")).quantize(Decimal("0.01")),
                Decimal("100.00"),
            )

            budget = db.scalar(
                select(Budget).where(
                    Budget.scope_type == BudgetScopeType.product,
                    Budget.scope_id == product.id,
                    Budget.period == BudgetPeriod.monthly,
                    Budget.is_active.is_(True),
                )
            )

            if budget is None:
                budget = Budget(
                    scope_type=BudgetScopeType.product,
                    scope_id=product.id,
                    period=BudgetPeriod.monthly,
                    limit_amount=limit_amount,
                    warning_threshold=0.8,
                    currency="RUB",
                    is_active=True,
                )
                db.add(budget)
            else:
                budget.limit_amount = limit_amount
                budget.warning_threshold = 0.8
                budget.currency = "RUB"

            print(f"{product.name}: бюджет {limit_amount} RUB")

        db.commit()
        print(f"Настроено бюджетов: {len(products)}")


if __name__ == "__main__":
    main()
