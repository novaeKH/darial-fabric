from __future__ import annotations

import uuid

from sqlalchemy import text

from app.core.database import SessionLocal


PERMISSIONS = [
    ("platform.admin", "Полное управление платформой"),
    ("products.read", "Просмотр AI-продуктов"),
    ("products.manage", "Управление AI-продуктами"),
    ("runs.read", "Просмотр запусков"),
    ("economics.read", "Просмотр AI-экономики"),
    ("budgets.read", "Просмотр бюджетов"),
    ("budgets.manage", "Управление бюджетами"),
    ("policies.read", "Просмотр политик"),
    ("policies.manage", "Управление политиками"),
    ("violations.read", "Просмотр нарушений"),
    ("violations.manage", "Обработка нарушений"),
    ("reports.read", "Просмотр отчётов"),
    ("integrations.manage", "Управление интеграциями"),
    ("audit.read", "Просмотр аудита"),
    ("rbac.manage", "Управление доступами"),
]

ROLES = [
    {
        "code": "admin",
        "name": "Администратор",
        "description": "Полный доступ ко всем разделам Darial.",
        "permissions": [code for code, _ in PERMISSIONS],
    },
    {
        "code": "product_owner",
        "name": "Владелец AI-продукта",
        "description": "Управление своим продуктом, агентами, runs и результатами.",
        "permissions": [
            "products.read",
            "products.manage",
            "runs.read",
            "economics.read",
            "budgets.read",
            "violations.read",
            "reports.read",
        ],
    },
    {
        "code": "finops",
        "name": "AI FinOps",
        "description": "Экономика, бюджеты и управленческие отчёты.",
        "permissions": [
            "products.read",
            "runs.read",
            "economics.read",
            "budgets.read",
            "budgets.manage",
            "reports.read",
        ],
    },
    {
        "code": "security",
        "name": "Информационная безопасность",
        "description": "Политики, нарушения, аудит и интеграции.",
        "permissions": [
            "products.read",
            "runs.read",
            "policies.read",
            "policies.manage",
            "violations.read",
            "violations.manage",
            "integrations.manage",
            "audit.read",
        ],
    },
    {
        "code": "auditor",
        "name": "Аудитор",
        "description": "Только чтение отчётов, политик, runs и аудита.",
        "permissions": [
            "products.read",
            "runs.read",
            "economics.read",
            "budgets.read",
            "policies.read",
            "violations.read",
            "reports.read",
            "audit.read",
        ],
    },
]


def main() -> None:
    with SessionLocal() as db:
        from app.api.rbac_routes import ensure_tables
        ensure_tables(db)

        permission_ids = {}

        for code, name in PERMISSIONS:
            existing = db.execute(
                text("SELECT id FROM rbac_permissions WHERE code=:code"),
                {"code": code},
            ).scalar()

            permission_id = existing or str(uuid.uuid4())

            db.execute(
                text("""
                    INSERT INTO rbac_permissions (id, code, name)
                    VALUES (:id, :code, :name)
                    ON CONFLICT (code) DO UPDATE SET name=EXCLUDED.name
                """),
                {
                    "id": permission_id,
                    "code": code,
                    "name": name,
                },
            )
            permission_ids[code] = db.execute(
                text("SELECT id FROM rbac_permissions WHERE code=:code"),
                {"code": code},
            ).scalar_one()

        for role in ROLES:
            existing = db.execute(
                text("SELECT id FROM rbac_roles WHERE code=:code"),
                {"code": role["code"]},
            ).scalar()

            role_id = existing or str(uuid.uuid4())

            db.execute(
                text("""
                    INSERT INTO rbac_roles (
                        id, code, name, description, is_system
                    )
                    VALUES (
                        :id, :code, :name, :description, TRUE
                    )
                    ON CONFLICT (code) DO UPDATE SET
                        name=EXCLUDED.name,
                        description=EXCLUDED.description
                """),
                {
                    "id": role_id,
                    "code": role["code"],
                    "name": role["name"],
                    "description": role["description"],
                },
            )

            role_id = db.execute(
                text("SELECT id FROM rbac_roles WHERE code=:code"),
                {"code": role["code"]},
            ).scalar_one()

            db.execute(
                text("DELETE FROM rbac_role_permissions WHERE role_id=:role_id"),
                {"role_id": role_id},
            )

            for permission_code in role["permissions"]:
                db.execute(
                    text("""
                        INSERT INTO rbac_role_permissions (
                            role_id, permission_id
                        )
                        VALUES (:role_id, :permission_id)
                        ON CONFLICT DO NOTHING
                    """),
                    {
                        "role_id": role_id,
                        "permission_id": permission_ids[permission_code],
                    },
                )

            print(f"Role: {role['code']}")

        db.commit()
        print(f"Настроено ролей: {len(ROLES)}")


if __name__ == "__main__":
    main()
