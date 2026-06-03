"""Unit tests for web/routers/auth.py — POST /api/auth/telegram and GET /api/auth/me."""

import hashlib
import hmac
import time
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bot.config import Config
from web.main import create_app

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BOT_TOKEN = "1234567890:AAFakeTokenForTestingPurposesOnly"
JWT_SECRET = "test-super-secret-key-for-unit-tests"
TELEGRAM_ID = 123456789


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_valid_payload(
    bot_token: str = BOT_TOKEN,
    age_seconds: int = 0,
    telegram_id: int = TELEGRAM_ID,
    username: str = "alice",
    first_name: str = "Alice",
) -> dict:
    """Build a correctly signed Telegram Login Widget payload."""
    auth_date = int(time.time()) - age_seconds
    data: dict = {
        "id": str(telegram_id),
        "first_name": first_name,
        "username": username,
        "auth_date": str(auth_date),
    }
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    data["hash"] = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    # Return as ints for id/auth_date as the Telegram widget sends them.
    return {
        "id": telegram_id,
        "first_name": first_name,
        "username": username,
        "auth_date": auth_date,
        "hash": data["hash"],
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def web_config_open() -> Config:
    """Config with empty ALLOWED_USER_IDS (open mode)."""
    return Config(
        telegram_bot_token=BOT_TOKEN,
        anthropic_api_key="sk-ant-fake",
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret=JWT_SECRET,
        allowed_user_ids=[],
    )


@pytest.fixture
def web_config_allowlist() -> Config:
    """Config with ALLOWED_USER_IDS set to [TELEGRAM_ID]."""
    return Config(
        telegram_bot_token=BOT_TOKEN,
        anthropic_api_key="sk-ant-fake",
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret=JWT_SECRET,
        allowed_user_ids=[TELEGRAM_ID],
    )


@pytest.fixture
def app_open(web_config_open: Config) -> FastAPI:
    """FastAPI app in open mode (no user allowlist)."""
    with patch("web.main.init_db"):
        return create_app(web_config_open)


@pytest.fixture
def app_allowlist(web_config_allowlist: Config) -> FastAPI:
    """FastAPI app with ALLOWED_USER_IDS enforced."""
    with patch("web.main.init_db"):
        return create_app(web_config_allowlist)


# ---------------------------------------------------------------------------
# POST /api/auth/telegram — valid payload
# ---------------------------------------------------------------------------


def test_login_telegram_valid_payload_returns_200_with_token(app_open: FastAPI) -> None:
    """Valid Telegram widget payload returns HTTP 200 with a token."""
    payload = _make_valid_payload()
    with TestClient(app_open, raise_server_exceptions=True) as client:
        response = client.post("/api/auth/telegram", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert "token" in body
    assert isinstance(body["token"], str)
    assert len(body["token"]) > 0


def test_login_telegram_valid_payload_token_is_valid_jwt(app_open: FastAPI) -> None:
    """The returned token is a valid JWT that decodes with the correct sub claim."""
    import jwt as pyjwt

    payload = _make_valid_payload()
    with TestClient(app_open, raise_server_exceptions=True) as client:
        response = client.post("/api/auth/telegram", json=payload)
    token = response.json()["token"]
    claims = pyjwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    assert claims["sub"] == str(TELEGRAM_ID)


# ---------------------------------------------------------------------------
# POST /api/auth/telegram — tampered hash → 401
# ---------------------------------------------------------------------------


def test_login_telegram_tampered_hash_returns_401(app_open: FastAPI) -> None:
    """Tampered hash field causes HTTP 401."""
    payload = _make_valid_payload()
    payload["hash"] = "deadbeef" * 8  # wrong hash, correct length
    with TestClient(app_open, raise_server_exceptions=True) as client:
        response = client.post("/api/auth/telegram", json=payload)
    assert response.status_code == 401


def test_login_telegram_missing_hash_returns_401(app_open: FastAPI) -> None:
    """Missing hash field causes HTTP 401."""
    payload = _make_valid_payload()
    del payload["hash"]
    with TestClient(app_open, raise_server_exceptions=True) as client:
        response = client.post("/api/auth/telegram", json=payload)
    # Pydantic will reject the missing required field with 422.
    assert response.status_code in (401, 422)


# ---------------------------------------------------------------------------
# POST /api/auth/telegram — expired auth_date → 401
# ---------------------------------------------------------------------------


def test_login_telegram_expired_auth_date_returns_401(app_open: FastAPI) -> None:
    """auth_date older than 24 h causes HTTP 401."""
    payload = _make_valid_payload(age_seconds=86401)
    with TestClient(app_open, raise_server_exceptions=True) as client:
        response = client.post("/api/auth/telegram", json=payload)
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/auth/telegram — allowlist mode: unlisted user → 403
# ---------------------------------------------------------------------------


def test_login_telegram_unlisted_user_returns_403(app_allowlist: FastAPI) -> None:
    """Valid Telegram user not in ALLOWED_USER_IDS returns HTTP 403."""
    # Build a valid payload for a *different* user not in the allowlist.
    payload = _make_valid_payload(telegram_id=999999999)
    with TestClient(app_allowlist, raise_server_exceptions=True) as client:
        response = client.post("/api/auth/telegram", json=payload)
    assert response.status_code == 403


def test_login_telegram_listed_user_returns_200(app_allowlist: FastAPI) -> None:
    """Valid Telegram user in ALLOWED_USER_IDS returns HTTP 200."""
    payload = _make_valid_payload(telegram_id=TELEGRAM_ID)
    with TestClient(app_allowlist, raise_server_exceptions=True) as client:
        response = client.post("/api/auth/telegram", json=payload)
    assert response.status_code == 200
    assert "token" in response.json()


# ---------------------------------------------------------------------------
# POST /api/auth/telegram — open mode: any valid user gets token
# ---------------------------------------------------------------------------


def test_login_telegram_open_mode_any_user_gets_token(app_open: FastAPI) -> None:
    """In open mode (empty ALLOWED_USER_IDS), any valid Telegram user receives a token."""
    payload = _make_valid_payload(telegram_id=777777777)
    with TestClient(app_open, raise_server_exceptions=True) as client:
        response = client.post("/api/auth/telegram", json=payload)
    assert response.status_code == 200
    assert "token" in response.json()


# ---------------------------------------------------------------------------
# GET /api/auth/me — no token → 401
# ---------------------------------------------------------------------------


def test_auth_me_without_token_returns_401(app_open: FastAPI) -> None:
    """GET /api/auth/me without Authorization header returns HTTP 401."""
    with TestClient(app_open, raise_server_exceptions=True) as client:
        response = client.get("/api/auth/me")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/auth/me — invalid token → 401
# ---------------------------------------------------------------------------


def test_auth_me_with_invalid_token_returns_401(app_open: FastAPI) -> None:
    """GET /api/auth/me with a garbage token returns HTTP 401."""
    with TestClient(app_open, raise_server_exceptions=True) as client:
        response = client.get("/api/auth/me", headers={"Authorization": "Bearer garbage.token"})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/auth/me — valid token → 200 with claims
# ---------------------------------------------------------------------------


def test_auth_me_with_valid_token_returns_200(app_open: FastAPI) -> None:
    """GET /api/auth/me with a valid JWT returns HTTP 200 and the decoded claims."""
    # First obtain a token via login.
    payload = _make_valid_payload()
    with TestClient(app_open, raise_server_exceptions=True) as client:
        login_response = client.post("/api/auth/telegram", json=payload)
    assert login_response.status_code == 200
    token = login_response.json()["token"]

    with TestClient(app_open, raise_server_exceptions=True) as client:
        me_response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_response.status_code == 200
    claims = me_response.json()
    assert claims["sub"] == str(TELEGRAM_ID)


def test_auth_me_end_to_end_full_flow(app_open: FastAPI) -> None:
    """Full login → /me round-trip returns the correct telegram_id in sub claim."""
    payload = _make_valid_payload(telegram_id=TELEGRAM_ID, username="alice", first_name="Alice")
    with TestClient(app_open, raise_server_exceptions=True) as client:
        login_resp = client.post("/api/auth/telegram", json=payload)
        assert login_resp.status_code == 200
        token = login_resp.json()["token"]

        me_resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me_resp.status_code == 200
        assert me_resp.json()["sub"] == str(TELEGRAM_ID)


# ---------------------------------------------------------------------------
# POST /api/auth/telegram — misconfiguration (missing bot token / jwt secret)
# ---------------------------------------------------------------------------


def test_login_telegram_missing_bot_token_returns_500() -> None:
    """POST /api/auth/telegram returns 500 when bot_token is absent from config."""
    from unittest.mock import MagicMock

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from web.routers.auth import router

    mini_app = FastAPI()
    # Attach a config that has no telegram_bot_token attribute.
    mini_app.state.config = MagicMock(spec=[])  # spec=[] → no attributes
    mini_app.include_router(router)

    payload = _make_valid_payload()
    with TestClient(mini_app, raise_server_exceptions=False) as client:
        response = client.post("/api/auth/telegram", json=payload)
    assert response.status_code == 500


# ---------------------------------------------------------------------------
# Router registration — routers are mounted in create_app
# ---------------------------------------------------------------------------


def test_create_app_registers_auth_telegram_route(app_open: FastAPI) -> None:
    """The /api/auth/telegram route is registered on the app."""
    routes = {route.path for route in app_open.routes}  # type: ignore[attr-defined]
    assert "/api/auth/telegram" in routes


def test_create_app_registers_auth_me_route(app_open: FastAPI) -> None:
    """The /api/auth/me route is registered on the app."""
    routes = {route.path for route in app_open.routes}  # type: ignore[attr-defined]
    assert "/api/auth/me" in routes
