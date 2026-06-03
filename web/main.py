"""FastAPI application factory for the tg-smart-inbox web UI companion."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bot.config import Config, get_config
from bot.db import init_db
from web.dependencies import get_current_user


def create_app(config: Config | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Initialises the DB session factory via the shared `bot.db.init_db`,
    adds CORS middleware, and registers all API routers under `/api/`.
    Raises ValueError when JWT_SECRET is not configured.
    """
    if config is None:
        config = get_config()

    if config.jwt_secret is None:
        raise ValueError(
            "JWT_SECRET must be set to start the web service. "
            "Add JWT_SECRET=<long-random-string> to your .env file."
        )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
        """Initialise shared resources on startup; clean up on shutdown."""
        init_db(config.database_url)
        yield

    app = FastAPI(title="tg-smart-inbox web API", lifespan=lifespan)

    # Store config on app.state so dependencies can read it.
    app.state.config = config

    # CORS — allow origins from config; fall back to wildcard for dev convenience.
    cors_origins: list[str] = getattr(config, "cors_origins", None) or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health-check endpoint — no auth required.
    @app.get("/api/health")
    async def health() -> dict:
        """Return service liveness status."""
        return {"status": "ok"}

    # Auth probe — protected; returns the current user's JWT payload.
    @app.get("/api/auth/me")
    async def auth_me(current_user: Annotated[dict, Depends(get_current_user)]) -> dict:
        """Return the authenticated user's token payload."""
        return current_user

    return app
