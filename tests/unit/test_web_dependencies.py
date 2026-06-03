"""Unit tests for web/dependencies.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Config
from web.dependencies import get_current_user, get_db_session

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
# get_current_user — invalid token
# ---------------------------------------------------------------------------


async def test_get_current_user_invalid_token_raises_401() -> None:
    """get_current_user raises HTTP 401 when verify_jwt_token raises HTTPException."""
    mock_request = MagicMock()
    mock_request.app.state.config = None

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad.token")

    # The stub web.auth.verify_jwt_token always raises 401.
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
    expected_payload = {"telegram_id": 42, "sub": "42"}

    with patch("web.dependencies.verify_jwt_token", return_value=expected_payload):
        result = await get_current_user(request=mock_request, credentials=credentials)

    assert result == expected_payload


# ---------------------------------------------------------------------------
# get_current_user — allowlist enforcement
# ---------------------------------------------------------------------------


async def test_get_current_user_allowlist_permits_listed_user() -> None:
    """get_current_user allows a user whose telegram_id is in ALLOWED_USER_IDS."""
    mock_request = MagicMock()
    config = MagicMock(spec=Config)
    config.allowed_user_ids = [123, 456]
    mock_request.app.state.config = config

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="tok")
    payload = {"telegram_id": 123}

    with patch("web.dependencies.verify_jwt_token", return_value=payload):
        result = await get_current_user(request=mock_request, credentials=credentials)

    assert result["telegram_id"] == 123


async def test_get_current_user_allowlist_rejects_unlisted_user() -> None:
    """get_current_user raises HTTP 403 when telegram_id is not in ALLOWED_USER_IDS."""
    mock_request = MagicMock()
    config = MagicMock(spec=Config)
    config.allowed_user_ids = [123, 456]
    mock_request.app.state.config = config

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="tok")
    payload = {"telegram_id": 999}

    with (
        patch("web.dependencies.verify_jwt_token", return_value=payload),
        pytest.raises(HTTPException) as exc_info,
    ):
        await get_current_user(request=mock_request, credentials=credentials)

    assert exc_info.value.status_code == 403


async def test_get_current_user_no_config_on_state_skips_allowlist() -> None:
    """get_current_user skips allowlist check when config is absent from app.state."""
    mock_request = MagicMock()
    # app.state has no config attribute
    del mock_request.app.state.config

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="tok")
    payload = {"telegram_id": 99}

    with patch("web.dependencies.verify_jwt_token", return_value=payload):
        result = await get_current_user(request=mock_request, credentials=credentials)

    assert result == payload
