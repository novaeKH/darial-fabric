from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
import re

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


# Most specific routes must be listed before broad prefixes.
ROUTE_RULES: tuple[RouteRule, ...] = (
    RouteRule("/api/observability/reports", ("reports.read", "platform.admin"), ("platform.admin",)),
    RouteRule("/api/observability/dashboard", ("economics.read", "platform.admin"), ("platform.admin",)),
    RouteRule("/api/observability/budgets", ("budgets.read", "platform.admin"), ("budgets.manage", "platform.admin")),
    RouteRule("/api/budgets", ("budgets.read", "platform.admin"), ("budgets.manage", "platform.admin")),
    RouteRule("/api/observability/policies", ("policies.read", "platform.admin"), ("policies.manage", "platform.admin")),
    RouteRule("/api/enterprise-policies", ("policies.read", "platform.admin"), ("policies.manage", "platform.admin")),
    RouteRule("/api/observability/violations", ("violations.read", "platform.admin"), ("violations.manage", "platform.admin")),
    RouteRule("/api/observability/audit", ("audit.read", "platform.admin"), ("platform.admin",)),
    RouteRule("/api/observability/runs", ("runs.read", "platform.admin"), ("platform.admin",)),
    RouteRule("/api/observability/agents", ("runs.read", "platform.admin"), ("platform.admin",)),
    RouteRule("/api/ai-products", ("products.read", "platform.admin"), ("products.manage", "platform.admin")),
    RouteRule("/api/agent-deployments", ("products.read", "platform.admin"), ("products.manage", "platform.admin")),
    RouteRule("/api/model-endpoints", ("products.read", "platform.admin"), ("products.manage", "platform.admin")),
    RouteRule("/api/agents", ("products.read", "platform.admin"), ("products.manage", "platform.admin")),
    RouteRule("/api/teams", ("products.read", "platform.admin"), ("platform.admin",)),
    RouteRule("/api/ingestion", ("integrations.manage", "platform.admin"), ("integrations.manage", "platform.admin")),
    RouteRule("/api/kafka", ("integrations.manage", "platform.admin"), ("integrations.manage", "platform.admin")),
    RouteRule("/api/rbac", ("rbac.manage", "platform.admin"), ("rbac.manage", "platform.admin")),
)


PUBLIC_PREFIXES = (
    "/api/health",
    "/docs",
    "/openapi.json",
)

PUBLIC_WRITE_PATHS = {
    "/api/ingestion/events",
    "/api/ingestion/events/batch",
}

PERMISSIONS_LOOKUP_RE = re.compile(
    r"^/api/rbac/principals/[^/]+/permissions$"
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
            text("SELECT status FROM rbac_principals WHERE id=:principal_id"),
            {"principal_id": principal_id},
        ).scalar()
        if principal_status != "active":
            return set()

        rows = db.execute(
            text("""
                SELECT DISTINCT p.code
                FROM rbac_user_roles ur
                JOIN rbac_role_permissions rp ON rp.role_id = ur.role_id
                JOIN rbac_permissions p ON p.id = rp.permission_id
                WHERE ur.principal_id=:principal_id
            """),
            {"principal_id": principal_id},
        ).all()
        return {row[0] for row in rows}


def is_public_path(path: str, method: str) -> bool:
    if any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
        return True

    # Demo login bootstrap: list principals and fetch exactly one principal's
    # effective permissions. Other /api/rbac routes remain protected.
    if method in READ_METHODS and path == "/api/rbac/principals":
        return True
    if method in READ_METHODS and PERMISSIONS_LOOKUP_RE.fullmatch(path):
        return True

    # Telemetry uses deployment API keys, not an interactive principal.
    if method == "POST" and path in PUBLIC_WRITE_PATHS:
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
