from __future__ import annotations

from dataclasses import dataclass
from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class ProductScope:
    organization_wide: bool
    product_ids: frozenset[str]


def get_product_scope(db: Session, principal_id: str | None) -> ProductScope:
    if not principal_id:
        raise HTTPException(status_code=401, detail="Darial principal is required")

    rows = db.execute(
        text(
            """
            SELECT ur.scope_type, ur.scope_id
            FROM rbac_user_roles ur
            JOIN rbac_principals p ON p.id = ur.principal_id
            WHERE ur.principal_id=:principal_id
              AND p.status='active'
            """
        ),
        {"principal_id": principal_id},
    ).mappings().all()

    if not rows:
        raise HTTPException(status_code=403, detail="No active RBAC assignment")

    if any(row["scope_type"] == "organization" for row in rows):
        return ProductScope(True, frozenset())

    product_ids = frozenset(
        str(row["scope_id"])
        for row in rows
        if row["scope_type"] == "product" and row["scope_id"]
    )
    return ProductScope(False, product_ids)


def get_request_product_scope(request: Request, db: Session) -> ProductScope:
    return get_product_scope(db, getattr(request.state, "principal_id", None))


def ensure_product_access(scope: ProductScope, product_id: str) -> None:
    if scope.organization_wide:
        return
    if product_id not in scope.product_ids:
        raise HTTPException(
            status_code=403,
            detail="Product is outside the assigned RBAC scope",
        )
