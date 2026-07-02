from __future__ import annotations

from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.rbac_routes import ensure_tables
from app.core.database import SessionLocal

ROUTE_RULES = [
    ("/api/rbac", {"rbac.manage", "platform.admin"}),
    ("/api/observability/reports", {"reports.read", "platform.admin"}),
    ("/api/observability/budgets", {"budgets.read", "platform.admin"}),
    ("/api/budgets", {"budgets.manage", "platform.admin"}),
    ("/api/observability/policies", {"policies.read", "policies.manage", "platform.admin"}),
    ("/api/observability/violations", {"violations.read", "violations.manage", "platform.admin"}),
    ("/api/ingestion", {"integrations.manage", "platform.admin"}),
    ("/api/ai-products", {"products.read", "platform.admin"}),
    ("/api/agent-deployments", {"products.read", "platform.admin"}),
    ("/api/observability/runs", {"runs.read", "platform.admin"}),
    ("/api/observability/agents", {"runs.read", "platform.admin"}),
]


def _required(path: str) -> set[str] | None:
    for prefix, permissions in ROUTE_RULES:
        if path.startswith(prefix):
            return permissions
    return None


def _permissions(principal_id: str) -> set[str]:
    with SessionLocal() as db:
        ensure_tables(db)
        status = db.execute(
            text("SELECT status FROM rbac_principals WHERE id=:id"),
            {"id": principal_id},
        ).scalar()
        if status != "active":
            return set()

        rows = db.execute(
            text(
                """
                SELECT DISTINCT p.code
                FROM rbac_user_roles ur
                JOIN rbac_role_permissions rp ON rp.role_id=ur.role_id
                JOIN rbac_permissions p ON p.id=rp.permission_id
                WHERE ur.principal_id=:principal_id
                """
            ),
            {"principal_id": principal_id},
        ).all()
        return {row[0] for row in rows}


async def rbac_middleware(request: Request, call_next: Callable):
    path = request.url.path
    if not path.startswith("/api/"):
        return await call_next(request)

    # Session bootstrap endpoints remain readable before a role is selected.
    if path == "/api/rbac/principals" or path.endswith("/permissions"):
        return await call_next(request)

    required = _required(path)
    if not required:
        return await call_next(request)

    principal_id = request.headers.get("X-Darial-Principal")
    if not principal_id:
        return JSONResponse(status_code=401, content={"detail": "Select a Darial user"})

    permissions = _permissions(principal_id)
    if not permissions.intersection(required):
        return JSONResponse(
            status_code=403,
            content={"detail": "Permission denied", "required_permissions": sorted(required)},
        )

    request.state.principal_id = principal_id
    request.state.permissions = permissions
    return await call_next(request)
