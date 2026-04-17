from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from bot.exceptions import InvalidLanguageError, InvalidTimezoneError
from bot.models.user_settings import UserSettings
from bot.repositories.user_settings import UserSettingsRepository

DEFAULT_TIMEZONE = "UTC"
DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES: frozenset[str] = frozenset({"ru", "en"})


def _derive_language(language_code: str | None) -> str:
    """Return 'ru' if language_code starts with 'ru', else the default ('en')."""
    if language_code and language_code.lower().startswith("ru"):
        return "ru"
    return DEFAULT_LANGUAGE


class UserSettingsService:
    """Business logic for reading and updating per-user settings."""

    def __init__(self, session: AsyncSession, repo: UserSettingsRepository) -> None:
        self._session = session
        self._repo = repo

    async def get_timezone(self, user_id: int) -> str:
        """Return the user's IANA timezone string, or 'UTC' if not configured."""
        settings = await self._repo.get(user_id)
        if settings is None:
            return DEFAULT_TIMEZONE
        return settings.timezone

    async def has_timezone(self, user_id: int) -> bool:
        """Return True if the user has explicitly set a timezone (row exists in DB)."""
        settings = await self._repo.get(user_id)
        return settings is not None

    async def set_timezone(self, user_id: int, tz_name: str) -> None:
        """Validate and persist the user's timezone; raises InvalidTimezoneError on bad name."""
        try:
            ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise InvalidTimezoneError(f"Invalid IANA timezone: {tz_name!r}") from exc
        await self._repo.set_timezone(user_id, tz_name)
        await self._session.commit()

    async def get_language(self, user_id: int) -> str:
        """Return the user's language code, or the default ('en') if not configured."""
        settings = await self._repo.get(user_id)
        if settings is None:
            return DEFAULT_LANGUAGE
        return settings.language

    async def set_language(self, user_id: int, language: str) -> None:
        """Validate and persist the user's language; raises InvalidLanguageError on bad code."""
        if language not in SUPPORTED_LANGUAGES:
            raise InvalidLanguageError(f"Unsupported language: {language!r}")
        await self._repo.set_language(user_id, language)
        await self._session.commit()

    async def ensure_user_settings(
        self, user_id: int, language_code: str | None = None
    ) -> UserSettings:
        """Return existing UserSettings, or create one with language derived from Telegram."""
        existing = await self._repo.get(user_id)
        if existing is not None:
            return existing
        language = _derive_language(language_code)
        settings = await self._repo.get_or_create(user_id, language=language)
        await self._session.commit()
        return settings
