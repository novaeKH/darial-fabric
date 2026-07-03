from __future__ import annotations

import json
import uuid

from sqlalchemy import text

from app.core.database import SessionLocal

POLICIES = [
    {
        "name": "Лимит стоимости одного run",
        "code": "MAX_RUN_COST",
        "description": "Выявляет отдельные запуски с аномально высокой стоимостью.",
        "rule_type": "max_run_cost",
        "config": {"limit": 2.5},
        "severity": "warning",
        "mode": "monitor",
    },
    {
        "name": "Максимальная latency",
        "code": "MAX_RUN_LATENCY",
        "description": "Контролирует время выполнения AI-сценария.",
        "rule_type": "max_latency_ms",
        "config": {"limit": 15000},
        "severity": "warning",
        "mode": "monitor",
    },
    {
        "name": "Обязательный business outcome",
        "code": "REQUIRE_BUSINESS_OUTCOME",
        "description": "Каждый успешный run должен регистрировать бизнес-результат.",
        "rule_type": "require_outcome",
        "config": {},
        "severity": "info",
        "mode": "monitor",
    },
    {
        "name": "Разрешённые LLM-модели",
        "code": "ALLOWED_MODELS",
        "description": "Ограничивает использование незарегистрированных моделей.",
        "rule_type": "allowed_models",
        "config": {
            "models": [
                "qwen-72b-demo",
                "gpt-4.1-mini-demo",
                "claude-3-5-sonnet-demo"
            ]
        },
        "severity": "critical",
        "mode": "block",
    },
    {
        "name": "Запрещённые инструменты",
        "code": "PROHIBITED_TOOLS",
        "description": "Блокирует опасные инструменты и команды.",
        "rule_type": "prohibited_tools",
        "config": {"tools": ["shell_exec", "env_reader", "prod_db_write"]},
        "severity": "critical",
        "mode": "block",
    },
    {
        "name": "Лимит повторных попыток",
        "code": "MAX_RETRIES",
        "description": "Выявляет циклы и excessive retries.",
        "rule_type": "max_retries",
        "config": {"limit": 3},
        "severity": "warning",
        "mode": "monitor",
    },
]


def main() -> None:
    with SessionLocal() as db:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS governance_policies (
                    id VARCHAR(64) PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    code VARCHAR(128) NOT NULL UNIQUE,
                    description TEXT,
                    scope_type VARCHAR(32) NOT NULL DEFAULT 'organization',
                    scope_id VARCHAR(64),
                    rule_type VARCHAR(64) NOT NULL,
                    config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    severity VARCHAR(32) NOT NULL DEFAULT 'warning',
                    mode VARCHAR(32) NOT NULL DEFAULT 'monitor',
                    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
        )

        for policy in POLICIES:
            db.execute(
                text(
                    """
                    INSERT INTO governance_policies (
                        id, name, code, description, scope_type, scope_id,
                        rule_type, config_json, severity, mode, is_enabled
                    )
                    VALUES (
                        :id, :name, :code, :description, 'organization', NULL,
                        :rule_type, CAST(:config_json AS JSONB),
                        :severity, :mode, TRUE
                    )
                    ON CONFLICT (code) DO UPDATE SET
                        name = EXCLUDED.name,
                        description = EXCLUDED.description,
                        rule_type = EXCLUDED.rule_type,
                        config_json = EXCLUDED.config_json,
                        severity = EXCLUDED.severity,
                        mode = EXCLUDED.mode,
                        updated_at = NOW()
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "name": policy["name"],
                    "code": policy["code"],
                    "description": policy["description"],
                    "rule_type": policy["rule_type"],
                    "config_json": json.dumps(policy["config"]),
                    "severity": policy["severity"],
                    "mode": policy["mode"],
                },
            )
            print(f"Policy: {policy['code']}")

        db.commit()
        print(f"Настроено политик: {len(POLICIES)}")


if __name__ == "__main__":
    main()
