from decimal import Decimal

from app import models  # noqa: F401
from app.core.database import Base, SessionLocal, engine
from app.models.base import Agent, Team
from app.models.observability import (
    AIProduct,
    AgentDeployment,
    Environment,
    HostingType,
    ModelEndpoint,
)


def get_product(db, *, name: str, team_id: str, business_unit: str) -> AIProduct:
    product = (
        db.query(AIProduct)
        .filter(AIProduct.name == name, AIProduct.owner_team_id == team_id)
        .first()
    )
    if product:
        return product
    product = AIProduct(
        name=name,
        owner_team_id=team_id,
        business_unit=business_unit,
        description=f"Demo AI product for {business_unit}",
        criticality="medium",
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


def get_deployment(db, *, product: AIProduct, agent: Agent) -> AgentDeployment:
    deployment = (
        db.query(AgentDeployment)
        .filter(
            AgentDeployment.product_id == product.id,
            AgentDeployment.agent_id == agent.id,
            AgentDeployment.environment == Environment.prod,
            AgentDeployment.version == "1.0.0",
        )
        .first()
    )
    if deployment:
        return deployment
    deployment = AgentDeployment(
        product_id=product.id,
        agent_id=agent.id,
        version="1.0.0",
        environment=Environment.prod,
        cluster="demo-cluster",
        namespace="ai-products",
        service_name=agent.name,
        framework="custom-python",
    )
    db.add(deployment)
    db.commit()
    db.refresh(deployment)
    return deployment


def get_model_endpoint(db) -> ModelEndpoint:
    endpoint = (
        db.query(ModelEndpoint)
        .filter(
            ModelEndpoint.provider == "internal",
            ModelEndpoint.model_name == "qwen-72b-demo",
            ModelEndpoint.is_active.is_(True),
        )
        .first()
    )
    if endpoint:
        return endpoint
    endpoint = ModelEndpoint(
        provider="internal",
        model_name="qwen-72b-demo",
        deployment_name="corporate-llm-gateway",
        hosting_type=HostingType.internal_api,
        currency="RUB",
        input_price_per_million=Decimal("120"),
        output_price_per_million=Decimal("360"),
        cached_input_price_per_million=Decimal("30"),
        reasoning_price_per_million=Decimal("360"),
        gpu_hour_price=Decimal("0"),
    )
    db.add(endpoint)
    db.commit()
    db.refresh(endpoint)
    return endpoint


def seed_observability():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        team = db.query(Team).order_by(Team.created_at.asc()).first()
        if not team:
            raise RuntimeError("Run the existing app.seed first: no teams were found")

        agent_names = ["research-agent", "data-agent", "qa-agent"]
        agents = {
            agent.name: agent
            for agent in db.query(Agent).filter(Agent.name.in_(agent_names)).all()
        }
        missing = [name for name in agent_names if name not in agents]
        if missing:
            raise RuntimeError(
                "Run the existing app.seed first. Missing agents: " + ", ".join(missing)
            )

        products = [
            get_product(
                db,
                name="Legal Contract Analyzer",
                team_id=team.id,
                business_unit="Legal",
            ),
            get_product(
                db,
                name="Procurement Assistant",
                team_id=team.id,
                business_unit="Procurement",
            ),
            get_product(
                db,
                name="Internal Knowledge RAG",
                team_id=team.id,
                business_unit="Knowledge Management",
            ),
        ]

        get_deployment(db, product=products[0], agent=agents["research-agent"])
        get_deployment(db, product=products[1], agent=agents["data-agent"])
        get_deployment(db, product=products[2], agent=agents["qa-agent"])
        endpoint = get_model_endpoint(db)

        print("Observability seed completed successfully.")
        print(f"Created or reused {len(products)} AI products.")
        print(f"Model endpoint: {endpoint.provider}/{endpoint.model_name}")
    finally:
        db.close()


if __name__ == "__main__":
    seed_observability()
