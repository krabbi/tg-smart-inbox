"""Shared FastAPI dependencies for the web UI companion."""

from collections.abc import AsyncGenerator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import get_session_factory
from web.auth import verify_jwt_token

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession for the current request and close it afterwards."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> dict:
    """Extract and validate the JWT from the Authorization header.

    Raises HTTP 401 when the header is missing or the token is invalid/expired.
    Raises HTTP 403 when the token's telegram_id is not in ALLOWED_USER_IDS
    (allowlist mode only — when the list is non-empty).
    Returns the decoded JWT payload on success.
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    config = getattr(request.app.state, "config", None)
    secret: str | None = getattr(config, "jwt_secret", None)

    try:
        payload = verify_jwt_token(credentials.credentials, secret)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    # Enforce allowlist when ALLOWED_USER_IDS is configured.
    if config is not None and config.allowed_user_ids:
        telegram_id = payload.get("telegram_id")
        if telegram_id not in config.allowed_user_ids:
            raise HTTPException(status_code=403, detail="Forbidden")

    return payload
