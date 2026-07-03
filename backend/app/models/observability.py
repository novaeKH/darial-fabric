import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def uuid_str() -> str:
    return str(uuid.uuid4())


class ProductStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"
    archived = "archived"


class Environment(str, enum.Enum):
    dev = "dev"
    test = "test"
    stage = "stage"
    prod = "prod"


class RunStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class HostingType(str, enum.Enum):
    external_api = "external_api"
    internal_api = "internal_api"
    local = "local"


class TokenSource(str, enum.Enum):
    provider = "provider"
    gateway = "gateway"
    tokenizer = "tokenizer"
    estimated = "estimated"


class BudgetScopeType(str, enum.Enum):
    company = "company"
    team = "team"
    product = "product"
    agent = "agent"


class BudgetPeriod(str, enum.Enum):
    daily = "daily"
    monthly = "monthly"
    quarterly = "quarterly"
    yearly = "yearly"


class ViolationStatus(str, enum.Enum):
    open = "open"
    acknowledged = "acknowledged"
    resolved = "resolved"
    ignored = "ignored"


class AIProduct(Base):
    __tablename__ = "ai_products"
    __table_args__ = (
        UniqueConstraint("owner_team_id", "name", name="uq_ai_products_team_name"),
        Index("ix_ai_products_team_status", "owner_team_id", "status"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_team_id: Mapped[str] = mapped_column(String, ForeignKey("teams.id"))
    owner_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
    business_unit: Mapped[str | None] = mapped_column(String, nullable=True)
    criticality: Mapped[str] = mapped_column(String, default="medium")
    status: Mapped[ProductStatus] = mapped_column(
        Enum(ProductStatus), default=ProductStatus.active
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class AgentDeployment(Base):
    __tablename__ = "agent_deployments"
    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "agent_id",
            "environment",
            "version",
            name="uq_agent_deployment_version",
        ),
        Index("ix_agent_deployments_product_env", "product_id", "environment"),
        Index("ix_agent_deployments_agent_status", "agent_id", "status"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    product_id: Mapped[str] = mapped_column(String, ForeignKey("ai_products.id"))
    agent_id: Mapped[str] = mapped_column(String, ForeignKey("agents.id"))
    version: Mapped[str] = mapped_column(String, default="1.0.0")
    environment: Mapped[Environment] = mapped_column(
        Enum(Environment), default=Environment.dev
    )
    cluster: Mapped[str | None] = mapped_column(String, nullable=True)
    namespace: Mapped[str | None] = mapped_column(String, nullable=True)
    service_name: Mapped[str | None] = mapped_column(String, nullable=True)
    framework: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")
    deployed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ModelEndpoint(Base):
    __tablename__ = "model_endpoints"
    __table_args__ = (
        Index("ix_model_endpoints_provider_model", "provider", "model_name"),
        Index("ix_model_endpoints_active", "is_active"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    provider: Mapped[str] = mapped_column(String)
    model_name: Mapped[str] = mapped_column(String)
    deployment_name: Mapped[str | None] = mapped_column(String, nullable=True)
    hosting_type: Mapped[HostingType] = mapped_column(
        Enum(HostingType), default=HostingType.internal_api
    )
    currency: Mapped[str] = mapped_column(String, default="RUB")
    input_price_per_million: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), default=Decimal("0")
    )
    output_price_per_million: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), default=Decimal("0")
    )
    cached_input_price_per_million: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), default=Decimal("0")
    )
    reasoning_price_per_million: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), default=Decimal("0")
    )
    gpu_hour_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), default=Decimal("0")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    valid_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_trace", "trace_id"),
        Index("ix_agent_runs_product_created", "product_id", "created_at"),
        Index("ix_agent_runs_agent_status", "agent_id", "status"),
        Index("ix_agent_runs_environment_created", "environment", "created_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    trace_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    product_id: Mapped[str] = mapped_column(String, ForeignKey("ai_products.id"))
    agent_id: Mapped[str] = mapped_column(String, ForeignKey("agents.id"))
    deployment_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("agent_deployments.id"), nullable=True
    )
    workflow_name: Mapped[str] = mapped_column(String, default="default")
    environment: Mapped[Environment] = mapped_column(
        Enum(Environment), default=Environment.dev
    )
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus), default=RunStatus.running)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    total_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), default=Decimal("0")
    )
    error_type: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class LLMCall(Base):
    __tablename__ = "llm_calls"
    __table_args__ = (
        Index("ix_llm_calls_run_created", "run_id", "created_at"),
        Index("ix_llm_calls_model_created", "model_name", "created_at"),
        Index("ix_llm_calls_status", "status"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("agent_runs.id"))
    model_endpoint_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("model_endpoints.id"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String)
    model_name: Mapped[str] = mapped_column(String)
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    cached_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    reasoning_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    gpu_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, default="success")
    token_source: Mapped[TokenSource] = mapped_column(
        Enum(TokenSource), default=TokenSource.provider
    )
    estimated_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), default=Decimal("0")
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ToolCall(Base):
    __tablename__ = "tool_calls"
    __table_args__ = (
        Index("ix_tool_calls_run_created", "run_id", "created_at"),
        Index("ix_tool_calls_tool_status", "tool_name", "status"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("agent_runs.id"))
    tool_name: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="success")
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), default=Decimal("0")
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class BusinessOutcome(Base):
    __tablename__ = "business_outcomes"
    __table_args__ = (
        Index("ix_business_outcomes_run", "run_id"),
        Index("ix_business_outcomes_type_success", "outcome_type", "success"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("agent_runs.id"))
    outcome_type: Mapped[str] = mapped_column(String)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    quantity: Mapped[float] = mapped_column(Float, default=1.0)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    human_accepted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    time_saved_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_business_value: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 6), nullable=True
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (
        Index("ix_budgets_scope", "scope_type", "scope_id"),
        Index("ix_budgets_period", "period", "is_active"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    scope_type: Mapped[BudgetScopeType] = mapped_column(Enum(BudgetScopeType))
    scope_id: Mapped[str] = mapped_column(String)
    period: Mapped[BudgetPeriod] = mapped_column(Enum(BudgetPeriod))
    limit_amount: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    warning_threshold: Mapped[float] = mapped_column(Float, default=0.8)
    currency: Mapped[str] = mapped_column(String, default="RUB")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PolicyViolation(Base):
    __tablename__ = "policy_violations"
    __table_args__ = (
        Index("ix_policy_violations_status_severity", "status", "severity"),
        Index("ix_policy_violations_agent_detected", "agent_id", "detected_at"),
        Index("ix_policy_violations_product_detected", "product_id", "detected_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid_str)
    run_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("agent_runs.id"), nullable=True
    )
    product_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("ai_products.id"), nullable=True
    )
    agent_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("agents.id"), nullable=True
    )
    policy_code: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String, default="warning")
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[ViolationStatus] = mapped_column(
        Enum(ViolationStatus), default=ViolationStatus.open
    )
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
