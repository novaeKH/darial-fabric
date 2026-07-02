from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.rbac_routes import ensure_tables
from app.core.database import get_db

router = APIRouter(tags=["RBAC Session"])


@router.get("/rbac/principals/{principal_id}/permissions")
def principal_permissions(principal_id: str, db: Session = Depends(get_db)):
    ensure_tables(db)
    principal = db.execute(
        text("SELECT id, email, display_name, status FROM rbac_principals WHERE id=:id"),
        {"id": principal_id},
    ).mappings().first()
    if not principal:
        raise HTTPException(status_code=404, detail="Principal not found")

    permissions = db.execute(
        text(
            """
            SELECT DISTINCT p.code
            FROM rbac_user_roles ur
            JOIN rbac_role_permissions rp ON rp.role_id=ur.role_id
            JOIN rbac_permissions p ON p.id=rp.permission_id
            WHERE ur.principal_id=:principal_id
            ORDER BY p.code
            """
        ),
        {"principal_id": principal_id},
    ).all()

    return {
        "principal": dict(principal),
        "permissions": [row[0] for row in permissions],
    }
