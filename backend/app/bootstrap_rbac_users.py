from __future__ import annotations

import uuid
from sqlalchemy import text

from app.api.rbac_routes import ensure_tables
from app.core.database import SessionLocal

USERS = [
    ("admin@takt.local", "Takt Administrator", "admin"),
    ("finops@darial.local", "AI FinOps Manager", "finops"),
    ("security@darial.local", "Security Officer", "security"),
    ("owner@darial.local", "AI Product Owner", "product_owner"),
    ("auditor@darial.local", "External Auditor", "auditor"),
]


def main() -> None:
    with SessionLocal() as db:
        ensure_tables(db)
        for email, name, role_code in USERS:
            principal_id = db.execute(
                text("SELECT id FROM rbac_principals WHERE email=:email"),
                {"email": email},
            ).scalar()
            if not principal_id:
                principal_id = str(uuid.uuid4())
                db.execute(
                    text(
                        """
                        INSERT INTO rbac_principals (id, email, display_name, status)
                        VALUES (:id, :email, :name, 'active')
                        """
                    ),
                    {"id": principal_id, "email": email, "name": name},
                )

            role_id = db.execute(
                text("SELECT id FROM rbac_roles WHERE code=:code"),
                {"code": role_code},
            ).scalar_one()

            exists = db.execute(
                text(
                    """
                    SELECT id FROM rbac_user_roles
                    WHERE principal_id=:principal_id
                      AND role_id=:role_id
                      AND scope_type='organization'
                      AND scope_id IS NULL
                    """
                ),
                {"principal_id": principal_id, "role_id": role_id},
            ).scalar()

            if not exists:
                db.execute(
                    text(
                        """
                        INSERT INTO rbac_user_roles
                        (id, principal_id, role_id, scope_type, scope_id, assigned_by)
                        VALUES (:id, :principal_id, :role_id, 'organization', NULL, 'bootstrap')
                        """
                    ),
                    {"id": str(uuid.uuid4()), "principal_id": principal_id, "role_id": role_id},
                )
            print(f"{email} -> {role_code}")
        db.commit()


if __name__ == "__main__":
    main()
