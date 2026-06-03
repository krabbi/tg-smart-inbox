"""FastAPI application factory for the tg-smart-inbox web UI companion."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bot.config import Config, get_config
from bot.db import init_db
from web.routers import auth as auth_router


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

    # CORS — when explicit origins are configured, allow credentialed requests from
    # those origins only.  In dev mode (no origins configured) use a wildcard but
    # disable credentials: the CORS spec forbids Allow-Origin: * with credentials.
    if config.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Health-check endpoint — no auth required.
    @app.get("/api/health")
    async def health() -> dict:
        """Return service liveness status."""
        return {"status": "ok"}

    # Auth endpoints: POST /api/auth/telegram and GET /api/auth/me.
    app.include_router(auth_router.router)

    return app
