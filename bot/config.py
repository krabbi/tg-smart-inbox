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
    google_drive_credentials_file: str = "credentials.json"
    google_drive_folder_id: str = ""

    # Vector search — dimensionality of embeddings stored in pgvector columns.
    # Matches the voyage-3.5 output size (Voyage AI).
    embedding_dim: int = 1024

    @field_validator("allowed_user_ids", mode="before")
    @classmethod
    def parse_user_ids(cls, v: object) -> object:
        if isinstance(v, str):
            return [int(uid.strip()) for uid in v.split(",") if uid.strip()]
        if isinstance(v, int):
            return [v]
        return v


def get_config() -> Config:
    return Config()  # type: ignore[call-arg]
