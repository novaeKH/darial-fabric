from __future__ import annotations

import argparse

from app.core.database import SessionLocal
from app.models.observability import AgentRun, BusinessOutcome, LLMCall, ToolCall
from app.services.clickhouse_telemetry import ensure_clickhouse_schema, mirror_entity


MODELS = [
    ("agent_run", AgentRun),
    ("llm_call", LLMCall),
    ("tool_call", ToolCall),
    ("business_outcome", BusinessOutcome),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    ensure_clickhouse_schema()

    with SessionLocal() as db:
        for event_type, model in MODELS:
            query = db.query(model).order_by(model.id)
            if args.limit > 0:
                query = query.limit(args.limit)

            total = 0
            success = 0
            for item in query.yield_per(200):
                total += 1
                if mirror_entity(db, event_type, str(item.id)):
                    success += 1

            print(f"{event_type}: {success}/{total}")


if __name__ == "__main__":
    main()
