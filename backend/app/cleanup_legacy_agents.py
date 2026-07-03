from __future__ import annotations

import argparse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal
from app.models.base import Agent

LEGACY_NAMES = {
    "intake-agent","scanner-agent","classifier-agent","processor-agent","review-agent","delivery-agent",
    "intake_agent","scanner_agent","classifier_agent","processor_agent","review_agent","delivery_agent",
    "Intake Agent","Scanner Agent","Classifier Agent","Processor Agent","Review Agent","Delivery Agent",
}

def norm(value):
    return (value or "").strip().lower().replace("_", "-")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    targets = {norm(x) for x in LEGACY_NAMES}
    with SessionLocal() as db:
        agents = list(db.scalars(select(Agent)).all())
        matches = [a for a in agents if norm(getattr(a, "name", None)) in targets]

        if not matches:
            print("Старые demo-агенты не найдены.")
            return

        print("Найдены:")
        for agent in matches:
            print(f"  - {agent.name} ({agent.id})")

        if not args.apply:
            print("Предварительный просмотр. Для удаления добавьте --apply")
            return

        deleted = 0
        disabled = 0
        for agent in matches:
            name = agent.name
            try:
                db.delete(agent)
                db.commit()
                deleted += 1
                print(f"Удалён: {name}")
            except IntegrityError:
                db.rollback()
                current = db.get(Agent, agent.id)
                if current is not None and hasattr(current, "status"):
                    current.status = "disabled"
                    db.commit()
                    disabled += 1
                    print(f"Отключён: {name}")
                else:
                    print(f"Не удалось удалить: {name}")

        print(f"Готово. Удалено: {deleted}, отключено: {disabled}")

if __name__ == "__main__":
    main()
