"""Tests for docker-compose.yml web and nginx service definitions."""

import os

import pytest
import yaml  # noqa: F401 — used via yaml.safe_load in fixtures

COMPOSE_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "docker-compose.yml")
NGINX_CONF_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "nginx", "nginx.conf")


@pytest.fixture(scope="module")
def compose() -> dict:
    """Load the docker-compose.yml as a parsed dict."""
    with open(COMPOSE_PATH) as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def nginx_conf() -> str:
    """Load the nginx/nginx.conf as raw text."""
    with open(NGINX_CONF_PATH) as f:
        return f.read()


# ---------------------------------------------------------------------------
# docker-compose.yml — service presence
# ---------------------------------------------------------------------------


def test_compose_has_web_service(compose: dict) -> None:
    """docker-compose.yml defines a 'web' service."""
    assert "web" in compose["services"]


def test_compose_has_nginx_service(compose: dict) -> None:
    """docker-compose.yml defines an 'nginx' service."""
    assert "nginx" in compose["services"]


def test_compose_retains_bot_service(compose: dict) -> None:
    """docker-compose.yml still defines the original 'bot' service."""
    assert "bot" in compose["services"]


def test_compose_retains_db_service(compose: dict) -> None:
    """docker-compose.yml still defines the 'db' service."""
    assert "db" in compose["services"]


# ---------------------------------------------------------------------------
# web service — configuration
# ---------------------------------------------------------------------------


def test_web_service_builds_from_dot(compose: dict) -> None:
    """web service builds from the repo root (context: '.')."""
    web = compose["services"]["web"]
    assert web["build"]["context"] == "."


def test_web_service_uses_base_target(compose: dict) -> None:
    """web service uses the 'base' Dockerfile stage."""
    web = compose["services"]["web"]
    assert web["build"]["target"] == "base"


def test_web_service_command_uses_uvicorn(compose: dict) -> None:
    """web service command starts uvicorn on the FastAPI factory."""
    web = compose["services"]["web"]
    cmd = web["command"]
    assert "uvicorn" in cmd
    assert "web.main:create_app" in cmd
    assert "--factory" in cmd


def test_web_service_command_default_port(compose: dict) -> None:
    """web service command references the WEB_PORT env var with default 8000."""
    web = compose["services"]["web"]
    cmd = web["command"]
    assert "${WEB_PORT:-8000}" in cmd


def test_web_service_has_jwt_secret_env(compose: dict) -> None:
    """web service environment includes JWT_SECRET (required by web/main.py)."""
    web = compose["services"]["web"]
    env = web["environment"]
    # environment may be a list of strings or a dict
    env_str = str(env)
    assert "JWT_SECRET" in env_str


def test_web_service_has_database_url_env(compose: dict) -> None:
    """web service environment includes DATABASE_URL."""
    web = compose["services"]["web"]
    env = web["environment"]
    env_str = str(env)
    assert "DATABASE_URL" in env_str


def test_web_service_jwt_secret_required(compose: dict) -> None:
    """JWT_SECRET uses the :? syntax so Docker Compose fails fast when unset."""
    web = compose["services"]["web"]
    env = web["environment"]
    env_str = str(env)
    assert "JWT_SECRET:?" in env_str


def test_web_service_depends_on_db(compose: dict) -> None:
    """web service depends_on includes 'db' (waits for healthy DB)."""
    web = compose["services"]["web"]
    depends = web.get("depends_on", {})
    assert "db" in depends


def test_web_service_profile_is_web(compose: dict) -> None:
    """web service is in the 'web' profile."""
    web = compose["services"]["web"]
    assert "web" in web.get("profiles", [])


# ---------------------------------------------------------------------------
# nginx service — configuration
# ---------------------------------------------------------------------------


def test_nginx_service_uses_alpine_image(compose: dict) -> None:
    """nginx service uses the nginx:alpine image."""
    nginx = compose["services"]["nginx"]
    assert nginx["image"] == "nginx:alpine"


def test_nginx_service_exposes_port_80(compose: dict) -> None:
    """nginx service maps host port 80 to container port 80."""
    nginx = compose["services"]["nginx"]
    ports = nginx["ports"]
    assert "80:80" in ports


def test_nginx_service_mounts_conf(compose: dict) -> None:
    """nginx service mounts ./nginx/nginx.conf read-only."""
    nginx = compose["services"]["nginx"]
    volumes_str = str(nginx["volumes"])
    assert "nginx/nginx.conf" in volumes_str
    assert ":ro" in volumes_str


def test_nginx_service_mounts_frontend_dist(compose: dict) -> None:
    """nginx service mounts ./frontend/dist as the web root."""
    nginx = compose["services"]["nginx"]
    volumes_str = str(nginx["volumes"])
    assert "frontend/dist" in volumes_str


def test_nginx_service_depends_on_web(compose: dict) -> None:
    """nginx service depends on 'web'."""
    nginx = compose["services"]["nginx"]
    depends = nginx.get("depends_on", [])
    assert "web" in depends


def test_nginx_service_profile_is_web(compose: dict) -> None:
    """nginx service is in the 'web' profile."""
    nginx = compose["services"]["nginx"]
    assert "web" in nginx.get("profiles", [])


# ---------------------------------------------------------------------------
# nginx/nginx.conf — content validation
# ---------------------------------------------------------------------------


def test_nginx_conf_listens_on_port_80(nginx_conf: str) -> None:
    """nginx.conf configures the server to listen on port 80."""
    assert "listen 80;" in nginx_conf


def test_nginx_conf_proxies_api_to_web(nginx_conf: str) -> None:
    """nginx.conf proxies /api/ requests to the 'web' upstream container."""
    assert "location /api/" in nginx_conf
    assert "proxy_pass http://web:" in nginx_conf


def test_nginx_conf_hardcodes_port_8000(nginx_conf: str) -> None:
    """nginx.conf uses hardcoded port 8000 (nginx does not expand shell vars)."""
    assert "proxy_pass http://web:8000" in nginx_conf


def test_nginx_conf_serves_spa_root(nginx_conf: str) -> None:
    """nginx.conf has a root location that serves static files."""
    assert "location /" in nginx_conf
    assert "root /usr/share/nginx/html" in nginx_conf


def test_nginx_conf_spa_fallback(nginx_conf: str) -> None:
    """nginx.conf uses try_files with /index.html fallback for SPA routing."""
    assert "try_files" in nginx_conf
    assert "/index.html" in nginx_conf


def test_nginx_conf_sets_host_header(nginx_conf: str) -> None:
    """nginx.conf forwards the Host header to the upstream."""
    assert "proxy_set_header Host" in nginx_conf


def test_nginx_conf_sets_real_ip_header(nginx_conf: str) -> None:
    """nginx.conf forwards the client IP via X-Real-IP."""
    assert "proxy_set_header X-Real-IP" in nginx_conf


# ---------------------------------------------------------------------------
# Dockerfile — web/ is copied
# ---------------------------------------------------------------------------


def test_dockerfile_copies_web_directory() -> None:
    """Dockerfile copies the web/ package into the image."""
    dockerfile_path = os.path.join(os.path.dirname(__file__), "..", "..", "Dockerfile")
    with open(dockerfile_path) as f:
        content = f.read()
    assert "COPY web/ web/" in content
