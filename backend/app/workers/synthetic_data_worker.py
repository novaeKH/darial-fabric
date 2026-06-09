import time
from datetime import datetime

from app.core.config import settings
from app.core.database import SessionLocal
from app.services.synthetic_agent_service import run_synthetic_generation_once


def main():
    print("Synthetic Data Agent worker started.")
    print(f"Interval: {settings.SYNTHETIC_AGENT_INTERVAL_SECONDS} seconds")

    while True:
        db = SessionLocal()

        try:
            result = run_synthetic_generation_once(db)
            print(f"[{datetime.utcnow().isoformat()}] {result}")
        except Exception as exc:
            print(f"[{datetime.utcnow().isoformat()}] Worker error: {exc}")
        finally:
            db.close()

        time.sleep(settings.SYNTHETIC_AGENT_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()