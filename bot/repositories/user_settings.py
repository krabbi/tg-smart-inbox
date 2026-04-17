from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.user_settings import UserSettings


class UserSettingsRepository:
    """CRUD access for UserSettings records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: int) -> UserSettings | None:
        """Return UserSettings for user_id or None if it does not exist."""
        result = await self._session.execute(
            select(UserSettings).where(UserSettings.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(
        self, user_id: int, *, timezone: str = "UTC", language: str = "en"
    ) -> UserSettings:
        """Return existing UserSettings or create a new one with the given defaults."""
        existing = await self.get(user_id)
        if existing is not None:
            return existing
        settings = UserSettings(user_id=user_id, timezone=timezone, language=language)
        self._session.add(settings)
        await self._session.flush()
        await self._session.refresh(settings)
        return settings

    async def set_timezone(self, user_id: int, tz_name: str) -> UserSettings:
        """Set the timezone for user_id, creating the row if needed; flush only."""
        settings = await self.get_or_create(user_id)
        settings.timezone = tz_name
        await self._session.flush()
        await self._session.refresh(settings)
        return settings

    async def set_language(self, user_id: int, language: str) -> UserSettings:
        """Set the language for user_id, creating the row if needed; flush only."""
        settings = await self.get_or_create(user_id)
        settings.language = language
        await self._session.flush()
        await self._session.refresh(settings)
        return settings
