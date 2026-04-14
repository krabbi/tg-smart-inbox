from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from bot.exceptions import InvalidTimezoneError
from bot.models.user_settings import UserSettings
from bot.repositories.user_settings import UserSettingsRepository
from bot.services.user_settings_service import DEFAULT_TIMEZONE, UserSettingsService


def make_service() -> tuple[UserSettingsService, UserSettingsRepository, AsyncSession]:
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    repo = MagicMock(spec=UserSettingsRepository)
    svc = UserSettingsService(session=session, repo=repo)
    return svc, repo, session


async def test_get_timezone_returns_stored_value() -> None:
    svc, repo, _ = make_service()
    settings = MagicMock(spec=UserSettings)
    settings.timezone = "Europe/Moscow"
    repo.get = AsyncMock(return_value=settings)

    result = await svc.get_timezone(user_id=42)

    repo.get.assert_awaited_once_with(42)
    assert result == "Europe/Moscow"


async def test_get_timezone_returns_default_when_missing() -> None:
    svc, repo, _ = make_service()
    repo.get = AsyncMock(return_value=None)

    result = await svc.get_timezone(user_id=42)

    repo.get.assert_awaited_once_with(42)
    assert result == DEFAULT_TIMEZONE
    assert result == "UTC"


async def test_set_timezone_persists_valid_iana_name() -> None:
    svc, repo, session = make_service()
    repo.set_timezone = AsyncMock(return_value=MagicMock(spec=UserSettings))

    await svc.set_timezone(user_id=42, tz_name="Europe/Moscow")

    repo.set_timezone.assert_awaited_once_with(42, "Europe/Moscow")
    session.commit.assert_awaited_once()


async def test_set_timezone_accepts_utc() -> None:
    svc, repo, session = make_service()
    repo.set_timezone = AsyncMock(return_value=MagicMock(spec=UserSettings))

    await svc.set_timezone(user_id=42, tz_name="UTC")

    repo.set_timezone.assert_awaited_once_with(42, "UTC")
    session.commit.assert_awaited_once()


async def test_set_timezone_rejects_invalid_name() -> None:
    svc, repo, session = make_service()
    repo.set_timezone = AsyncMock()

    with pytest.raises(InvalidTimezoneError):
        await svc.set_timezone(user_id=42, tz_name="Not/A_Real_Zone")

    repo.set_timezone.assert_not_awaited()
    session.commit.assert_not_awaited()


async def test_set_timezone_rejects_empty_string() -> None:
    svc, repo, session = make_service()
    repo.set_timezone = AsyncMock()

    with pytest.raises(InvalidTimezoneError):
        await svc.set_timezone(user_id=42, tz_name="")

    repo.set_timezone.assert_not_awaited()
    session.commit.assert_not_awaited()


async def test_set_timezone_rejects_path_traversal() -> None:
    svc, repo, session = make_service()
    repo.set_timezone = AsyncMock()

    with pytest.raises(InvalidTimezoneError):
        await svc.set_timezone(user_id=42, tz_name="../etc/passwd")

    repo.set_timezone.assert_not_awaited()
    session.commit.assert_not_awaited()
