from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AIProductCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str | None = None
    owner_team_id: str
    owner_user_id: str | None = None
    business_unit: str | None = None
    criticality: str = "medium"


class AIProductRead(BaseModel):
    id: str
    name: str
    description: str | None
    owner_team_id: str
    owner_user_id: str | None
    business_unit: str | None
    criticality: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentDeploymentCreate(BaseModel):
    product_id: str
    agent_id: str
    version: str = "1.0.0"
    environment: str = "dev"
    cluster: str | None = None
    namespace: str | None = None
    service_name: str | None = None
    framework: str | None = None


class AgentDeploymentRead(BaseModel):
    id: str
    product_id: str
    agent_id: str
    version: str
    environment: str
    cluster: str | None
    namespace: str | None
    service_name: str | None
    framework: str | None
    status: str
    deployed_at: datetime
    last_seen_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class ModelEndpointCreate(BaseModel):
    provider: str
    model_name: str
    deployment_name: str | None = None
    hosting_type: str = "internal_api"
    currency: str = "RUB"
    input_price_per_million: float = Field(default=0, ge=0)
    output_price_per_million: float = Field(default=0, ge=0)
    cached_input_price_per_million: float = Field(default=0, ge=0)
    reasoning_price_per_million: float = Field(default=0, ge=0)
    gpu_hour_price: float = Field(default=0, ge=0)


class ModelEndpointRead(BaseModel):
    id: str
    provider: str
    model_name: str
    deployment_name: str | None
    hosting_type: str
    currency: str
    input_price_per_million: float
    output_price_per_million: float
    cached_input_price_per_million: float
    reasoning_price_per_million: float
    gpu_hour_price: float
    is_active: bool
    valid_from: datetime
    valid_to: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RunStartRequest(BaseModel):
    product_id: str
    deployment_id: str | None = None
    trace_id: str | None = None
    workflow_name: str = "default"
    environment: str = "dev"
    metadata_json: dict[str, Any] | None = None


class RunFinishRequest(BaseModel):
    status: str = "completed"
    error_type: str | None = None
    metadata_json: dict[str, Any] | None = None


class AgentRunRead(BaseModel):
    id: str
    trace_id: str
    product_id: str
    agent_id: str
    deployment_id: str | None
    workflow_name: str
    environment: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    latency_ms: int | None
    request_count: int
    total_cost: float
    error_type: str | None
    metadata_json: dict[str, Any] | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LLMCallCreate(BaseModel):
    model_endpoint_id: str | None = None
    provider: str
    model_name: str
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cached_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    gpu_seconds: float = Field(default=0, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    status: str = "success"
    token_source: str = "provider"
    metadata_json: dict[str, Any] | None = None


class LLMCallRead(BaseModel):
    id: str
    run_id: str
    model_endpoint_id: str | None
    provider: str
    model_name: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    reasoning_tokens: int
    gpu_seconds: float
    latency_ms: int | None
    status: str
    token_source: str
    estimated_cost: float
    metadata_json: dict[str, Any] | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ToolCallCreate(BaseModel):
    tool_name: str
    status: str = "success"
    latency_ms: int | None = Field(default=None, ge=0)
    estimated_cost: float = Field(default=0, ge=0)
    metadata_json: dict[str, Any] | None = None


class ToolCallRead(BaseModel):
    id: str
    run_id: str
    tool_name: str
    status: str
    latency_ms: int | None
    estimated_cost: float
    metadata_json: dict[str, Any] | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BusinessOutcomeCreate(BaseModel):
    outcome_type: str
    success: bool = True
    quantity: float = Field(default=1.0, ge=0)
    quality_score: float | None = Field(default=None, ge=0, le=1)
    human_accepted: bool | None = None
    time_saved_minutes: float | None = Field(default=None, ge=0)
    estimated_business_value: float | None = Field(default=None, ge=0)
    metadata_json: dict[str, Any] | None = None


class BusinessOutcomeRead(BaseModel):
    id: str
    run_id: str
    outcome_type: str
    success: bool
    quantity: float
    quality_score: float | None
    human_accepted: bool | None
    time_saved_minutes: float | None
    estimated_business_value: float | None
    metadata_json: dict[str, Any] | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DashboardSummary(BaseModel):
    period_from: datetime
    period_to: datetime
    total_runs: int
    successful_runs: int
    failed_runs: int
    success_rate: float
    total_requests: int
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    reasoning_tokens: int
    total_tokens: int
    total_cost: float
    failed_run_cost: float
    waste_rate: float
    successful_outcomes: float
    cost_per_successful_run: float | None
    cost_per_outcome: float | None
    average_latency_ms: float | None
