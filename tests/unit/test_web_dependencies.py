"""Unit tests for web/dependencies.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Config
from web.auth import create_jwt, verify_jwt_token
from web.dependencies import get_current_user, get_db_session

JWT_SECRET = "test-super-secret-key-for-unit-tests"
TELEGRAM_ID = 123456789

# ---------------------------------------------------------------------------
# get_db_session
# ---------------------------------------------------------------------------


async def test_get_db_session_yields_async_session() -> None:
    """get_db_session yields an AsyncSession and closes it after the request."""
    mock_session = MagicMock(spec=AsyncSession)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_factory = MagicMock(return_value=mock_session)

    with patch("web.dependencies.get_session_factory", return_value=mock_factory):
        gen = get_db_session()
        session = await gen.__anext__()
        assert session is mock_session
        # Exhaust the generator (simulates end of request)
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

    mock_session.__aexit__.assert_awaited_once()


# ---------------------------------------------------------------------------
# get_current_user — missing credentials
# ---------------------------------------------------------------------------


async def test_get_current_user_no_credentials_raises_401() -> None:
    """get_current_user raises HTTP 401 when no Bearer token is provided."""
    mock_request = MagicMock()
    mock_request.app.state.config = None

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(request=mock_request, credentials=None)

    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# get_current_user — invalid / expired token
# ---------------------------------------------------------------------------


async def test_get_current_user_invalid_token_raises_401() -> None:
    """get_current_user raises HTTP 401 when verify_jwt_token raises InvalidTokenError."""
    mock_request = MagicMock()
    mock_request.app.state.config = None

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad.token")

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(request=mock_request, credentials=credentials)

    assert exc_info.value.status_code == 401


async def test_get_current_user_expired_token_raises_401() -> None:
    """get_current_user raises HTTP 401 for an expired JWT."""
    mock_request = MagicMock()
    config = MagicMock(spec=Config)
    config.jwt_secret = JWT_SECRET
    config.allowed_user_ids = []
    mock_request.app.state.config = config

    # Build a token that expired 10 seconds ago.
    expired_token = create_jwt(TELEGRAM_ID, JWT_SECRET, ttl_seconds=-10)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=expired_token)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(request=mock_request, credentials=credentials)

    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# get_current_user — valid token, no allowlist
# ---------------------------------------------------------------------------


async def test_get_current_user_valid_token_no_allowlist() -> None:
    """get_current_user returns payload when token is valid and allowlist is empty."""
    mock_request = MagicMock()
    config = MagicMock(spec=Config)
    config.allowed_user_ids = []
    mock_request.app.state.config = config

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="good.token")
    expected_payload = {"sub": str(TELEGRAM_ID), "exp": 9999999999}

    with patch("web.dependencies.verify_jwt_token", return_value=expected_payload):
        result = await get_current_user(request=mock_request, credentials=credentials)

    assert result == expected_payload


async def test_get_current_user_no_config_on_state_skips_allowlist() -> None:
    """get_current_user skips allowlist check when config is absent from app.state."""
    mock_request = MagicMock()
    # app.state has no config attribute
    del mock_request.app.state.config

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="tok")
    payload = {"sub": str(TELEGRAM_ID)}

    with patch("web.dependencies.verify_jwt_token", return_value=payload):
        result = await get_current_user(request=mock_request, credentials=credentials)

    assert result == payload


# ---------------------------------------------------------------------------
# get_current_user — allowlist enforcement (reads "sub" claim)
# ---------------------------------------------------------------------------


async def test_get_current_user_allowlist_permits_listed_user() -> None:
    """get_current_user allows a user whose sub claim is in ALLOWED_USER_IDS."""
    mock_request = MagicMock()
    config = MagicMock(spec=Config)
    config.allowed_user_ids = [123, 456]
    mock_request.app.state.config = config

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="tok")
    # sub must be a string (JWT spec) — get_current_user converts to int for the check.
    payload = {"sub": "123"}

    with patch("web.dependencies.verify_jwt_token", return_value=payload):
        result = await get_current_user(request=mock_request, credentials=credentials)

    assert result["sub"] == "123"


async def test_get_current_user_allowlist_rejects_unlisted_user() -> None:
    """get_current_user raises HTTP 403 when sub claim is not in ALLOWED_USER_IDS."""
    mock_request = MagicMock()
    config = MagicMock(spec=Config)
    config.allowed_user_ids = [123, 456]
    mock_request.app.state.config = config

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="tok")
    payload = {"sub": "999"}

    with (
        patch("web.dependencies.verify_jwt_token", return_value=payload),
        pytest.raises(HTTPException) as exc_info,
    ):
        await get_current_user(request=mock_request, credentials=credentials)

    assert exc_info.value.status_code == 403


async def test_get_current_user_allowlist_rejects_missing_sub() -> None:
    """get_current_user raises HTTP 403 when the sub claim is absent from the payload."""
    mock_request = MagicMock()
    config = MagicMock(spec=Config)
    config.allowed_user_ids = [123]
    mock_request.app.state.config = config

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="tok")
    # Payload without sub — simulates a token from a different issuer.
    payload: dict = {}

    with (
        patch("web.dependencies.verify_jwt_token", return_value=payload),
        pytest.raises(HTTPException) as exc_info,
    ):
        await get_current_user(request=mock_request, credentials=credentials)

    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# verify_jwt_token — secret=None branch (used by the FastAPI dep)
# ---------------------------------------------------------------------------


def test_verify_jwt_token_secret_none_raises_invalid_token_error() -> None:
    """verify_jwt_token raises jwt.InvalidTokenError when secret is None."""
    with pytest.raises(jwt.InvalidTokenError):
        verify_jwt_token("any.token.here", secret=None)


def test_verify_jwt_token_valid_token_and_secret_returns_payload() -> None:
    """verify_jwt_token returns the decoded claims for a valid token+secret pair."""
    token = create_jwt(TELEGRAM_ID, JWT_SECRET)
    claims = verify_jwt_token(token, secret=JWT_SECRET)

    assert claims["sub"] == str(TELEGRAM_ID)
    assert "exp" in claims


def test_verify_jwt_token_wrong_secret_raises() -> None:
    """verify_jwt_token raises jwt.InvalidTokenError when the secret is wrong."""
    token = create_jwt(TELEGRAM_ID, JWT_SECRET)
    with pytest.raises(jwt.InvalidTokenError):
        verify_jwt_token(token, secret="wrong-secret")


def test_verify_jwt_token_expired_token_raises() -> None:
    """verify_jwt_token raises jwt.ExpiredSignatureError for an expired token."""
    token = create_jwt(TELEGRAM_ID, JWT_SECRET, ttl_seconds=-10)
    with pytest.raises(jwt.ExpiredSignatureError):
        verify_jwt_token(token, secret=JWT_SECRET)
