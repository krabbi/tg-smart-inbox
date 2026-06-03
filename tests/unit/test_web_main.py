"""Unit tests for web/main.py — FastAPI app factory."""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from bot.config import Config
from web.main import create_app


@pytest.fixture
def web_config() -> Config:
    """Minimal Config with JWT_SECRET set."""
    return Config(
        telegram_bot_token="1234567890:AAFakeTokenForTestingPurposesOnly",
        anthropic_api_key="sk-ant-fake",
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret="test-secret-key-for-unit-tests",
        allowed_user_ids=[],
    )


@pytest.fixture
def app(web_config: Config) -> FastAPI:
    """Create a FastAPI app with test config (no lifespan DB init)."""
    with patch("web.main.init_db"):
        return create_app(web_config)


def test_create_app_returns_fastapi_instance(web_config: Config) -> None:
    """create_app() returns a FastAPI application object."""
    with patch("web.main.init_db"):
        result = create_app(web_config)
    assert isinstance(result, FastAPI)


def test_create_app_raises_without_jwt_secret() -> None:
    """create_app() raises ValueError when jwt_secret is None."""
    config = Config(
        telegram_bot_token="1234567890:AAFakeTokenForTestingPurposesOnly",
        anthropic_api_key="sk-ant-fake",
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret=None,
        allowed_user_ids=[],
    )
    with pytest.raises(ValueError, match="JWT_SECRET"):
        create_app(config)


def test_health_endpoint_returns_200(app: FastAPI) -> None:
    """GET /api/health returns HTTP 200 with {"status": "ok"}."""
    with TestClient(app, raise_server_exceptions=True) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_auth_me_without_token_returns_401(app: FastAPI) -> None:
    """GET /api/auth/me without Authorization header returns HTTP 401."""
    with TestClient(app, raise_server_exceptions=True) as client:
        response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_auth_me_with_invalid_token_returns_401(app: FastAPI) -> None:
    """GET /api/auth/me with invalid Bearer token returns HTTP 401."""
    with TestClient(app, raise_server_exceptions=True) as client:
        response = client.get("/api/auth/me", headers={"Authorization": "Bearer invalid.token"})
    assert response.status_code == 401


def test_cors_headers_present(app: FastAPI) -> None:
    """CORS headers are present on responses when Origin header is sent."""
    with TestClient(app, raise_server_exceptions=True) as client:
        response = client.get("/api/health", headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 200
    assert "access-control-allow-origin" in response.headers


def test_cors_wildcard_no_credentials_when_no_origins_configured(web_config: Config) -> None:
    """When cors_origins is empty, allow_origins=* and allow_credentials=False (dev mode)."""
    web_config.cors_origins = []
    with patch("web.main.init_db"):
        dev_app = create_app(web_config)
    with TestClient(dev_app, raise_server_exceptions=True) as client:
        response = client.get("/api/health", headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "*"
    # Credentials must NOT be true when wildcard is used.
    assert response.headers.get("access-control-allow-credentials") != "true"


def test_cors_specific_origin_with_credentials_when_origins_configured() -> None:
    """When cors_origins is set, allow_credentials=True and only listed origins are reflected."""
    allowed_origin = "https://app.example.com"
    config = Config(
        telegram_bot_token="1234567890:AAFakeTokenForTestingPurposesOnly",
        anthropic_api_key="sk-ant-fake",
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret="test-secret-key-for-unit-tests",
        allowed_user_ids=[],
        cors_origins=[allowed_origin],
    )
    with patch("web.main.init_db"):
        prod_app = create_app(config)
    with TestClient(prod_app, raise_server_exceptions=True) as client:
        response = client.get("/api/health", headers={"Origin": allowed_origin})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == allowed_origin
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_cors_unlisted_origin_not_reflected_when_origins_configured() -> None:
    """When cors_origins is set, an unlisted origin does not get an Allow-Origin header."""
    config = Config(
        telegram_bot_token="1234567890:AAFakeTokenForTestingPurposesOnly",
        anthropic_api_key="sk-ant-fake",
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret="test-secret-key-for-unit-tests",
        allowed_user_ids=[],
        cors_origins=["https://app.example.com"],
    )
    with patch("web.main.init_db"):
        prod_app = create_app(config)
    with TestClient(prod_app, raise_server_exceptions=True) as client:
        response = client.get("/api/health", headers={"Origin": "https://evil.example.com"})
    assert response.status_code == 200
    # Starlette omits the header entirely for disallowed origins.
    assert response.headers.get("access-control-allow-origin") != "https://evil.example.com"


async def test_health_endpoint_async(app: FastAPI) -> None:
    """GET /api/health returns 200 via async HTTPX client."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_lifespan_calls_init_db(web_config: Config) -> None:
    """App lifespan calls init_db with the configured database_url on startup."""
    with patch("web.main.init_db") as mock_init_db:
        test_app = create_app(web_config)
        # TestClient triggers lifespan startup/shutdown via its context manager.
        with TestClient(test_app, raise_server_exceptions=True):
            pass
    mock_init_db.assert_called_once_with(web_config.database_url)
