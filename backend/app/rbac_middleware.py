from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.database import SessionLocal
from app.api.rbac_routes import ensure_tables


READ_METHODS = {"GET", "HEAD", "OPTIONS"}
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass(frozen=True)
class RouteRule:
    prefix: str
    read_permissions: tuple[str, ...] = ()
    write_permissions: tuple[str, ...] = ()


ROUTE_RULES: tuple[RouteRule, ...] = (
    RouteRule(
        "/api/observability/reports",
        read_permissions=("reports.read", "platform.admin"),
        write_permissions=("platform.admin",),
    ),
    RouteRule(
        "/api/observability/budgets",
        read_permissions=("budgets.read", "platform.admin"),
        write_permissions=("budgets.manage", "platform.admin"),
    ),
    RouteRule(
        "/api/budgets",
        read_permissions=("budgets.read", "platform.admin"),
        write_permissions=("budgets.manage", "platform.admin"),
    ),
    RouteRule(
        "/api/observability/policies",
        read_permissions=("policies.read", "platform.admin"),
        write_permissions=("policies.manage", "platform.admin"),
    ),
    RouteRule(
        "/api/observability/violations",
        read_permissions=("violations.read", "platform.admin"),
        write_permissions=("violations.manage", "platform.admin"),
    ),
    RouteRule(
        "/api/ingestion",
        read_permissions=("integrations.manage", "platform.admin"),
        write_permissions=("integrations.manage", "platform.admin"),
    ),
    RouteRule(
        "/api/rbac",
        read_permissions=("rbac.manage", "platform.admin"),
        write_permissions=("rbac.manage", "platform.admin"),
    ),
    RouteRule(
        "/api/ai-products",
        read_permissions=("products.read", "platform.admin"),
        write_permissions=("platform.admin",),
    ),
    RouteRule(
        "/api/agent-deployments",
        read_permissions=("products.read", "platform.admin"),
        write_permissions=("platform.admin",),
    ),
    RouteRule(
        "/api/observability/runs",
        read_permissions=("runs.read", "platform.admin"),
        write_permissions=("platform.admin",),
    ),
    RouteRule(
        "/api/observability/agents",
        read_permissions=("runs.read", "platform.admin"),
        write_permissions=("platform.admin",),
    ),
    RouteRule(
        "/api/observability/audit",
        read_permissions=("audit.read", "platform.admin"),
        write_permissions=("platform.admin",),
    ),
)


PUBLIC_PREFIXES = (
    "/api/health",
    "/docs",
    "/openapi.json",
)

PUBLIC_EXACT_PREFIXES = (
    "/api/rbac/principals",
)


def required_permissions(path: str, method: str) -> tuple[str, ...] | None:
    for rule in ROUTE_RULES:
        if not path.startswith(rule.prefix):
            continue

        if method in READ_METHODS:
            return rule.read_permissions or None

        if method in WRITE_METHODS:
            return rule.write_permissions or None

        return None

    return None


def load_permissions(principal_id: str) -> set[str]:
    with SessionLocal() as db:
        ensure_tables(db)

        principal_status = db.execute(
            text("""
                SELECT status
                FROM rbac_principals
                WHERE id=:principal_id
            """),
            {"principal_id": principal_id},
        ).scalar()

        if principal_status != "active":
            return set()

        rows = db.execute(
            text("""
                SELECT DISTINCT p.code
                FROM rbac_user_roles ur
                JOIN rbac_role_permissions rp
                  ON rp.role_id = ur.role_id
                JOIN rbac_permissions p
                  ON p.id = rp.permission_id
                WHERE ur.principal_id=:principal_id
            """),
            {"principal_id": principal_id},
        ).all()

        return {row[0] for row in rows}


def is_public_path(path: str, method: str) -> bool:
    if any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
        return True

    # Session switcher must be able to list principals and read permissions
    # before the principal header is selected.
    if method in READ_METHODS and any(
        path.startswith(prefix) for prefix in PUBLIC_EXACT_PREFIXES
    ):
        return True

    return False


async def rbac_middleware(request: Request, call_next: Callable):
    path = request.url.path
    method = request.method.upper()

    if not path.startswith("/api/") or is_public_path(path, method):
        return await call_next(request)

    required = required_permissions(path, method)
    if not required:
        return await call_next(request)

    principal_id = request.headers.get("X-Darial-Principal")
    if not principal_id:
        return JSONResponse(
            status_code=401,
            content={
                "detail": "Choose a Darial principal",
                "required_permissions": list(required),
            },
        )

    permissions = load_permissions(principal_id)

    if not permissions.intersection(required):
        return JSONResponse(
            status_code=403,
            content={
                "detail": "Permission denied",
                "method": method,
                "path": path,
                "required_permissions": list(required),
            },
        )

    request.state.principal_id = principal_id
    request.state.permissions = permissions
    return await call_next(request)
