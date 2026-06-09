

import hashlib
import secrets
from dataclasses import dataclass

from fastapi import Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.base import Agent


AGENT_KEY_PREFIX = "swf_agent_"
DEMO_AGENT_KEY_PREFIX = "swf_demo_"
API_KEY_PREVIEW_LENGTH = 12


@dataclass(frozen=True)
class AuthenticatedAgent:
    id: str
    name: str
    role: str | None
    status: str | None
    api_key_prefix: str | None


def generate_agent_api_key(prefix: str = AGENT_KEY_PREFIX) -> str:
    """
    Generate a new agent API key.

    The full key should be shown only once to the caller.
    Only hash_api_key(key) should be stored in the database.
    """
    token = secrets.token_urlsafe(32)
    return f"{prefix}{token}"


def hash_api_key(api_key: str) -> str:
    """
    Hash an API key for database storage and lookup.

    SHA-256 is enough for this MVP because generated API keys are high-entropy random secrets.
    For human passwords use a slow password hashing algorithm instead.
    """
    normalized_key = api_key.strip()
    return hashlib.sha256(normalized_key.encode("utf-8")).hexdigest()


def api_key_preview(api_key: str) -> str:
    clean_key = api_key.strip()
    if len(clean_key) <= API_KEY_PREVIEW_LENGTH:
        return clean_key
    return f"{clean_key[:API_KEY_PREVIEW_LENGTH]}..."


def get_agent_by_api_key(db: Session, api_key: str | None) -> Agent | None:
    if not api_key:
        return None

    clean_key = api_key.strip()
    if not clean_key:
        return None

    key_hash = hash_api_key(clean_key)
    return db.query(Agent).filter(Agent.api_key_hash == key_hash).first()


def to_authenticated_agent(agent: Agent) -> AuthenticatedAgent:
    return AuthenticatedAgent(
        id=agent.id,
        name=agent.name,
        role=agent.role,
        status=agent.status,
        api_key_prefix=getattr(agent, "api_key_prefix", None),
    )


def require_agent_api_key(
    x_agent_key: str | None = Header(default=None, alias="X-Agent-Key"),
) -> AuthenticatedAgent:
    """
    FastAPI dependency for production-like agent authentication.

    The backend derives current agent identity from X-Agent-Key instead of trusting agent_id
    sent by a client.
    """
    if not x_agent_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing_agent_api_key",
        )

    db = SessionLocal()
    try:
        agent = get_agent_by_api_key(db, x_agent_key)
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid_agent_api_key",
            )

        if agent.status != "active":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="agent_is_not_active",
            )

        return to_authenticated_agent(agent)
    finally:
        db.close()


def optional_agent_api_key(
    x_agent_key: str | None = Header(default=None, alias="X-Agent-Key"),
) -> AuthenticatedAgent | None:
    """
    Optional version for endpoints that support both demo mode and API-key mode.
    """
    if not x_agent_key:
        return None

    return require_agent_api_key(x_agent_key=x_agent_key)