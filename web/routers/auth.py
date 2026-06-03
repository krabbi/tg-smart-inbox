"""Auth router — POST /api/auth/telegram and GET /api/auth/me."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from web.auth import create_jwt, verify_telegram_login
from web.dependencies import get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


class TelegramLoginRequest(BaseModel):
    """Payload sent by the Telegram Login Widget JavaScript callback."""

    id: int
    first_name: str = ""
    last_name: str = ""
    username: str = ""
    photo_url: str = ""
    auth_date: int
    hash: str


@router.post("/telegram")
async def login_telegram(body: TelegramLoginRequest, request: Request) -> dict:
    """Verify a Telegram Login Widget payload and issue a JWT on success.

    Returns HTTP 401 when the payload hash is invalid or auth_date is expired.
    Returns HTTP 403 when the Telegram user is not in ALLOWED_USER_IDS (allowlist mode).
    Returns {"token": "<jwt>"} on success.
    """
    config = getattr(request.app.state, "config", None)
    bot_token: str | None = getattr(config, "telegram_bot_token", None)
    jwt_secret: str | None = getattr(config, "jwt_secret", None)

    if bot_token is None or jwt_secret is None:
        raise HTTPException(status_code=500, detail="Server misconfiguration")

    # Convert Pydantic model to plain dict for verify_telegram_login.
    # Exclude fields that are empty strings — the Widget only sends set fields.
    data = {k: str(v) for k, v in body.model_dump().items() if v != "" and v != 0}
    # Ensure id and auth_date are always present as strings (they are non-optional).
    data["id"] = str(body.id)
    data["auth_date"] = str(body.auth_date)

    if not verify_telegram_login(data, bot_token):
        raise HTTPException(status_code=401, detail="Invalid or expired Telegram login")

    # Allowlist check: skip when ALLOWED_USER_IDS is empty (open mode).
    if config is not None and config.allowed_user_ids and body.id not in config.allowed_user_ids:
        raise HTTPException(status_code=403, detail="Forbidden")

    token = create_jwt(body.id, jwt_secret)
    return {"token": token}


@router.get("/me")
async def auth_me(current_user: Annotated[dict, Depends(get_current_user)]) -> dict:
    """Return the authenticated user's JWT claims.

    Protected by the get_current_user dependency — returns HTTP 401 when the
    Authorization header is absent or carries an invalid/expired token.
    """
    return current_user
