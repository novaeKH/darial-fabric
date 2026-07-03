from __future__ import annotations

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.base import Agent
from app.models.observability import AgentDeployment

RENAMES = {
    "qa-agent": "Knowledge RAG Agent",
    "data-agent": "Procurement Analysis Agent",
    "research-agent": "Legal Contract Agent",
}

SERVICE_NAMES = {
    "Knowledge RAG Agent": "knowledge-rag-agent",
    "Procurement Analysis Agent": "procurement-analysis-agent",
    "Legal Contract Agent": "legal-contract-agent",
}


def main() -> None:
    with SessionLocal() as db:
        agents = list(db.scalars(select(Agent)).all())
        changed = 0

        for agent in agents:
            new_name = RENAMES.get(agent.name)
            if not new_name:
                continue

            old_name = agent.name
            agent.name = new_name
            if hasattr(agent, "status"):
                agent.status = "active"

            deployments = list(
                db.scalars(
                    select(AgentDeployment).where(
                        AgentDeployment.agent_id == agent.id
                    )
                ).all()
            )
            for deployment in deployments:
                deployment.service_name = SERVICE_NAMES[new_name]
                deployment.status = "active"

            changed += 1
            print(f"{old_name} -> {new_name}")

        db.commit()
        print(f"Обновлено агентов: {changed}")


if __name__ == "__main__":
    main()
