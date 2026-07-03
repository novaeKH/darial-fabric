import argparse
import random
import uuid
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from app import models  # noqa: F401
from app.core.database import Base, SessionLocal, engine
from app.models.base import Agent
from app.models.observability import (
    AIProduct,
    AgentDeployment,
    AgentRun,
    Budget,
    BudgetPeriod,
    BudgetScopeType,
    BusinessOutcome,
    Environment,
    LLMCall,
    ModelEndpoint,
    PolicyViolation,
    RunStatus,
    TokenSource,
    ToolCall,
    ViolationStatus,
)

DEMO_MARKER = "stage2_demo_telemetry"
MILLION = Decimal("1000000")
SECONDS_PER_HOUR = Decimal("3600")
MONEY_STEP = Decimal("0.000001")

PRODUCT_CONFIGS = {
    "Legal Contract Analyzer": {
        "agent_name": "research-agent",
        "workflow": "contract-analysis",
        "outcome_type": "contract_checked",
        "base_runs_per_day": 4,
        "input_range": (7000, 18000),
        "output_range": (900, 2600),
        "cached_share": (0.08, 0.28),
        "reasoning_range": (300, 1500),
        "latency_range": (5500, 19000),
        "failure_rate": 0.08,
        "retry_rate": 0.13,
        "quality_range": (0.86, 0.97),
        "time_saved_range": (22, 48),
        "value_per_outcome": (900, 2200),
        "tools": ["s3_document_reader", "contract_clause_checker", "risk_classifier"],
        "monthly_budget": Decimal("42000"),
    },
    "Procurement Assistant": {
        "agent_name": "data-agent",
        "workflow": "supplier-comparison",
        "outcome_type": "supplier_offer_compared",
        "base_runs_per_day": 6,
        "input_range": (3500, 11500),
        "output_range": (650, 2100),
        "cached_share": (0.05, 0.18),
        "reasoning_range": (150, 1100),
        "latency_range": (3800, 14500),
        "failure_rate": 0.14,
        "retry_rate": 0.28,
        "quality_range": (0.78, 0.93),
        "time_saved_range": (12, 34),
        "value_per_outcome": (450, 1300),
        "tools": ["supplier_registry", "price_normalizer", "erp_connector"],
        "monthly_budget": Decimal("36000"),
    },
    "Internal Knowledge RAG": {
        "agent_name": "qa-agent",
        "workflow": "knowledge-search",
        "outcome_type": "question_resolved",
        "base_runs_per_day": 9,
        "input_range": (1800, 6800),
        "output_range": (250, 1150),
        "cached_share": (0.18, 0.48),
        "reasoning_range": (0, 450),
        "latency_range": (1200, 7200),
        "failure_rate": 0.06,
        "retry_rate": 0.09,
        "quality_range": (0.81, 0.95),
        "time_saved_range": (4, 16),
        "value_per_outcome": (180, 650),
        "tools": ["vector_search", "document_reranker", "knowledge_s3"],
        "monthly_budget": Decimal("28000"),
    },
}


def qmoney(value: Decimal) -> Decimal:
    return value.quantize(MONEY_STEP, rounding=ROUND_HALF_UP)


def calculate_cost(endpoint: ModelEndpoint, *, input_tokens: int, output_tokens: int,
                   cached_tokens: int, reasoning_tokens: int, gpu_seconds: float) -> Decimal:
    token_cost = (
        Decimal(input_tokens) * endpoint.input_price_per_million
        + Decimal(output_tokens) * endpoint.output_price_per_million
        + Decimal(cached_tokens) * endpoint.cached_input_price_per_million
        + Decimal(reasoning_tokens) * endpoint.reasoning_price_per_million
    ) / MILLION
    gpu_cost = (Decimal(str(gpu_seconds)) / SECONDS_PER_HOUR) * endpoint.gpu_hour_price
    return qmoney(token_cost + gpu_cost)


def clear_existing_demo(db) -> int:
    demo_runs = (
        db.query(AgentRun)
        .filter(AgentRun.metadata_json["demo_marker"].as_string() == DEMO_MARKER)
        .all()
    )
    run_ids = [run.id for run in demo_runs]
    if not run_ids:
        return 0

    db.query(PolicyViolation).filter(PolicyViolation.run_id.in_(run_ids)).delete(
        synchronize_session=False
    )
    db.query(BusinessOutcome).filter(BusinessOutcome.run_id.in_(run_ids)).delete(
        synchronize_session=False
    )
    db.query(ToolCall).filter(ToolCall.run_id.in_(run_ids)).delete(
        synchronize_session=False
    )
    db.query(LLMCall).filter(LLMCall.run_id.in_(run_ids)).delete(
        synchronize_session=False
    )
    db.query(AgentRun).filter(AgentRun.id.in_(run_ids)).delete(
        synchronize_session=False
    )
    db.commit()
    return len(run_ids)


def get_required_entities(db):
    endpoint = (
        db.query(ModelEndpoint)
        .filter(
            ModelEndpoint.provider == "internal",
            ModelEndpoint.model_name == "qwen-72b-demo",
            ModelEndpoint.is_active.is_(True),
        )
        .first()
    )
    if endpoint is None:
        raise RuntimeError("Model endpoint not found. Run: python -m app.observability_seed")

    result = []
    for product_name, cfg in PRODUCT_CONFIGS.items():
        product = db.query(AIProduct).filter(AIProduct.name == product_name).first()
        agent = db.query(Agent).filter(Agent.name == cfg["agent_name"]).first()
        if product is None or agent is None:
            raise RuntimeError(
                f"Missing product or agent for {product_name}. Run app.seed and app.observability_seed first."
            )
        deployment = (
            db.query(AgentDeployment)
            .filter(
                AgentDeployment.product_id == product.id,
                AgentDeployment.agent_id == agent.id,
                AgentDeployment.environment == Environment.prod,
            )
            .order_by(AgentDeployment.deployed_at.desc())
            .first()
        )
        if deployment is None:
            raise RuntimeError(f"Deployment not found for {product_name}")
        result.append((product, agent, deployment, cfg))
    return endpoint, result


def ensure_budgets(db, products):
    for product, _, _, cfg in products:
        budget = (
            db.query(Budget)
            .filter(
                Budget.scope_type == BudgetScopeType.product,
                Budget.scope_id == product.id,
                Budget.period == BudgetPeriod.monthly,
                Budget.is_active.is_(True),
            )
            .first()
        )
        if budget is None:
            db.add(
                Budget(
                    scope_type=BudgetScopeType.product,
                    scope_id=product.id,
                    period=BudgetPeriod.monthly,
                    limit_amount=cfg["monthly_budget"],
                    warning_threshold=0.8,
                    currency="RUB",
                    is_active=True,
                )
            )
    db.commit()


def create_run(db, rng, endpoint, product, agent, deployment, cfg, event_time):
    failed = rng.random() < cfg["failure_rate"]
    retry_count = 1 if rng.random() < cfg["retry_rate"] else 0
    if product.name == "Procurement Assistant" and rng.random() < 0.07:
        retry_count = rng.randint(2, 5)

    call_count = 1 + retry_count
    total_cost = Decimal("0")
    total_llm_latency = 0
    llm_rows = []

    for call_index in range(call_count):
        input_tokens = rng.randint(*cfg["input_range"])
        output_tokens = rng.randint(*cfg["output_range"])
        cached_tokens = int(input_tokens * rng.uniform(*cfg["cached_share"]))
        reasoning_tokens = rng.randint(*cfg["reasoning_range"])
        latency_ms = rng.randint(*cfg["latency_range"])
        status = "error" if failed and call_index == call_count - 1 else "success"
        gpu_seconds = round(latency_ms / 1000 * rng.uniform(0.55, 0.95), 3)
        cost = calculate_cost(
            endpoint,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            reasoning_tokens=reasoning_tokens,
            gpu_seconds=gpu_seconds,
        )
        total_cost += cost
        total_llm_latency += latency_ms
        llm_rows.append(
            LLMCall(
                run_id="PENDING",
                model_endpoint_id=endpoint.id,
                provider=endpoint.provider,
                model_name=endpoint.model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=cached_tokens,
                reasoning_tokens=reasoning_tokens,
                gpu_seconds=gpu_seconds,
                latency_ms=latency_ms,
                status=status,
                token_source=TokenSource.provider,
                estimated_cost=cost,
                metadata_json={
                    "demo_marker": DEMO_MARKER,
                    "attempt": call_index + 1,
                    "retry": call_index > 0,
                },
                created_at=event_time + timedelta(seconds=call_index * 2),
            )
        )

    tool_count = rng.randint(1, min(3, len(cfg["tools"])))
    selected_tools = rng.sample(cfg["tools"], k=tool_count)
    tool_rows = []
    tool_latency = 0
    for index, tool_name in enumerate(selected_tools):
        latency_ms = rng.randint(80, 1500)
        tool_latency += latency_ms
        tool_rows.append(
            ToolCall(
                run_id="PENDING",
                tool_name=tool_name,
                status="error" if failed and index == tool_count - 1 and rng.random() < 0.55 else "success",
                latency_ms=latency_ms,
                estimated_cost=Decimal("0"),
                metadata_json={"demo_marker": DEMO_MARKER},
                created_at=event_time + timedelta(seconds=1 + index),
            )
        )

    overhead_ms = rng.randint(150, 1100)
    latency_ms = total_llm_latency + tool_latency + overhead_ms
    finished_at = event_time + timedelta(milliseconds=latency_ms)
    run = AgentRun(
        trace_id=f"demo-{uuid.uuid4()}",
        product_id=product.id,
        agent_id=agent.id,
        deployment_id=deployment.id,
        workflow_name=cfg["workflow"],
        environment=Environment.prod,
        status=RunStatus.failed if failed else RunStatus.completed,
        started_at=event_time,
        finished_at=finished_at,
        latency_ms=latency_ms,
        request_count=call_count,
        total_cost=qmoney(total_cost),
        error_type=(rng.choice(["MODEL_TIMEOUT", "TOOL_ERROR", "VALIDATION_ERROR"]) if failed else None),
        metadata_json={
            "demo_marker": DEMO_MARKER,
            "source": "demo-generator",
            "retry_count": retry_count,
            "department": product.business_unit,
        },
        created_at=event_time,
    )
    db.add(run)
    db.flush()

    for row in llm_rows:
        row.run_id = run.id
        db.add(row)
    for row in tool_rows:
        row.run_id = run.id
        db.add(row)

    if not failed:
        quality = round(rng.uniform(*cfg["quality_range"]), 3)
        accepted = rng.random() < max(0.65, quality)
        outcome_success = accepted and quality >= 0.8
        db.add(
            BusinessOutcome(
                run_id=run.id,
                outcome_type=cfg["outcome_type"],
                success=outcome_success,
                quantity=1.0,
                quality_score=quality,
                human_accepted=accepted,
                time_saved_minutes=round(rng.uniform(*cfg["time_saved_range"]), 1),
                estimated_business_value=Decimal(str(rng.randint(*cfg["value_per_outcome"]))),
                metadata_json={"demo_marker": DEMO_MARKER},
                created_at=finished_at,
            )
        )

    if retry_count >= 3:
        db.add(
            PolicyViolation(
                run_id=run.id,
                product_id=product.id,
                agent_id=agent.id,
                policy_code="EXCESSIVE_RETRIES",
                severity="warning",
                description=f"Run produced {retry_count} retries and avoidable token spend.",
                status=ViolationStatus.open,
                details={"demo_marker": DEMO_MARKER, "retry_count": retry_count},
                detected_at=finished_at,
            )
        )
    elif failed and rng.random() < 0.45:
        db.add(
            PolicyViolation(
                run_id=run.id,
                product_id=product.id,
                agent_id=agent.id,
                policy_code="FAILED_RUN_COST",
                severity="info",
                description="Failed run consumed billable LLM resources.",
                status=ViolationStatus.open,
                details={"demo_marker": DEMO_MARKER, "cost": float(total_cost)},
                detected_at=finished_at,
            )
        )


def seed_demo_telemetry(days: int = 30, seed: int = 20260702, reset: bool = True):
    if days < 1 or days > 180:
        raise ValueError("days must be between 1 and 180")

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    rng = random.Random(seed)
    try:
        removed = clear_existing_demo(db) if reset else 0
        endpoint, products = get_required_entities(db)
        ensure_budgets(db, products)

        now = datetime.utcnow().replace(microsecond=0)
        created = 0
        for day_offset in range(days - 1, -1, -1):
            day_start = now - timedelta(days=day_offset)
            for product, agent, deployment, cfg in products:
                variation = rng.choice([-2, -1, 0, 0, 0, 1, 1, 2])
                run_count = max(1, cfg["base_runs_per_day"] + variation)
                for _ in range(run_count):
                    event_time = day_start.replace(
                        hour=rng.randint(7, 20),
                        minute=rng.randint(0, 59),
                        second=rng.randint(0, 59),
                    )
                    if event_time > now:
                        event_time = now - timedelta(minutes=rng.randint(1, 90))
                    create_run(
                        db,
                        rng,
                        endpoint,
                        product,
                        agent,
                        deployment,
                        cfg,
                        event_time,
                    )
                    created += 1
            db.commit()

        print("Demo telemetry seed completed successfully.")
        print(f"Removed previous demo runs: {removed}")
        print(f"Created runs: {created}")
        print(f"Period: {days} days")
        print(f"Random seed: {seed}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def parse_args():
    parser = argparse.ArgumentParser(description="Generate deterministic Darial demo telemetry")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20260702)
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="Append telemetry instead of replacing prior stage2 demo rows",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    seed_demo_telemetry(days=args.days, seed=args.seed, reset=not args.no_reset)
