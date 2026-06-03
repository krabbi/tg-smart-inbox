from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str
    anthropic_api_key: str
    database_url: str = "sqlite+aiosqlite:///data/bot.db"
    allowed_user_ids: list[int] = []

    # Voyage AI (optional — required only for semantic search / embeddings)
    voyage_api_key: str = ""

    # Groq (optional — required only for voice transcription)
    groq_api_key: str = ""

    # Google Drive (optional — required only for media handling)
    # OAuth 2.0 client secrets JSON (downloaded from Google Cloud Console
    # "OAuth 2.0 Client IDs"). Used once on first run to obtain user credentials.
    google_drive_credentials_file: str = "credentials.json"
    # Path where the obtained OAuth user token (with refresh token) is persisted
    # between runs. Must survive container restarts (mounted volume in Docker).
    google_drive_token_file: str = "token.json"
    google_drive_folder_id: str = ""

    # Vector search — dimensionality of embeddings stored in pgvector columns.
    # Matches the voyage-3.5 output size (Voyage AI).
    embedding_dim: int = 1024

    # Web UI companion (optional — only required when running the web service).
    # JWT_SECRET is validated at web app startup (web/main.py), not here, so the
    # bot process can start without it.
    jwt_secret: str | None = None
    web_port: int = 8000
    # Comma-separated list of allowed CORS origins for the web UI companion.
    # Non-empty → credentialed requests allowed from these origins only.
    # Empty (default) → wildcard "*" used without credentials (dev convenience).
    cors_origins: list[str] = []

    @field_validator("allowed_user_ids", mode="before")
    @classmethod
    def parse_user_ids(cls, v: object) -> object:
        if isinstance(v, str):
            return [int(uid.strip()) for uid in v.split(",") if uid.strip()]
        if isinstance(v, int):
            return [v]
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v


def get_config() -> Config:
    return Config()  # type: ignore[call-arg]
