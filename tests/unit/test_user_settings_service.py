from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from bot.exceptions import InvalidLanguageError, InvalidTimezoneError
from bot.models.user_settings import UserSettings
from bot.repositories.user_settings import UserSettingsRepository
from bot.services.user_settings_service import (
    DEFAULT_LANGUAGE,
    DEFAULT_TIMEZONE,
    UserSettingsService,
    _derive_language,
)


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


async def test_has_timezone_true_when_row_exists() -> None:
    svc, repo, _ = make_service()
    settings = MagicMock(spec=UserSettings)
    settings.timezone = "Europe/Moscow"
    repo.get = AsyncMock(return_value=settings)

    assert await svc.has_timezone(user_id=42) is True


async def test_has_timezone_false_when_row_missing() -> None:
    svc, repo, _ = make_service()
    repo.get = AsyncMock(return_value=None)

    assert await svc.has_timezone(user_id=42) is False


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


# --- language tests ---------------------------------------------------------


def test_derive_language_returns_ru_for_ru_prefix() -> None:
    assert _derive_language("ru") == "ru"
    assert _derive_language("ru-RU") == "ru"
    assert _derive_language("RU") == "ru"


def test_derive_language_returns_default_for_other_codes() -> None:
    assert _derive_language("en") == "en"
    assert _derive_language("en-US") == "en"
    assert _derive_language("de") == "en"
    assert _derive_language("fr-FR") == "en"


def test_derive_language_returns_default_for_none_or_empty() -> None:
    assert _derive_language(None) == "en"
    assert _derive_language("") == "en"


async def test_get_language_returns_stored_value() -> None:
    svc, repo, _ = make_service()
    settings = MagicMock(spec=UserSettings)
    settings.language = "ru"
    repo.get = AsyncMock(return_value=settings)

    result = await svc.get_language(user_id=42)

    repo.get.assert_awaited_once_with(42)
    assert result == "ru"


async def test_get_language_returns_default_when_missing() -> None:
    svc, repo, _ = make_service()
    repo.get = AsyncMock(return_value=None)

    result = await svc.get_language(user_id=42)

    repo.get.assert_awaited_once_with(42)
    assert result == DEFAULT_LANGUAGE
    assert result == "en"


async def test_set_language_persists_supported_code() -> None:
    svc, repo, session = make_service()
    repo.set_language = AsyncMock(return_value=MagicMock(spec=UserSettings))

    await svc.set_language(user_id=42, language="ru")

    repo.set_language.assert_awaited_once_with(42, "ru")
    session.commit.assert_awaited_once()


async def test_set_language_accepts_en() -> None:
    svc, repo, session = make_service()
    repo.set_language = AsyncMock(return_value=MagicMock(spec=UserSettings))

    await svc.set_language(user_id=42, language="en")

    repo.set_language.assert_awaited_once_with(42, "en")
    session.commit.assert_awaited_once()


async def test_set_language_rejects_unsupported_code() -> None:
    svc, repo, session = make_service()
    repo.set_language = AsyncMock()

    with pytest.raises(InvalidLanguageError):
        await svc.set_language(user_id=42, language="de")

    repo.set_language.assert_not_awaited()
    session.commit.assert_not_awaited()


async def test_set_language_rejects_empty_string() -> None:
    svc, repo, session = make_service()
    repo.set_language = AsyncMock()

    with pytest.raises(InvalidLanguageError):
        await svc.set_language(user_id=42, language="")

    repo.set_language.assert_not_awaited()
    session.commit.assert_not_awaited()


async def test_set_language_rejects_case_mismatch() -> None:
    svc, repo, session = make_service()
    repo.set_language = AsyncMock()

    with pytest.raises(InvalidLanguageError):
        await svc.set_language(user_id=42, language="RU")

    repo.set_language.assert_not_awaited()
    session.commit.assert_not_awaited()


async def test_ensure_user_settings_returns_existing_without_creating() -> None:
    svc, repo, session = make_service()
    existing = MagicMock(spec=UserSettings)
    existing.language = "ru"
    repo.get = AsyncMock(return_value=existing)
    repo.get_or_create = AsyncMock()

    result = await svc.ensure_user_settings(user_id=42, language_code="en-US")

    assert result is existing
    repo.get.assert_awaited_once_with(42)
    repo.get_or_create.assert_not_awaited()
    session.commit.assert_not_awaited()


async def test_ensure_user_settings_creates_with_ru_language() -> None:
    svc, repo, session = make_service()
    repo.get = AsyncMock(return_value=None)
    created = MagicMock(spec=UserSettings)
    created.language = "ru"
    repo.get_or_create = AsyncMock(return_value=created)

    result = await svc.ensure_user_settings(user_id=42, language_code="ru-RU")

    assert result is created
    repo.get_or_create.assert_awaited_once_with(42, language="ru")
    session.commit.assert_awaited_once()


async def test_ensure_user_settings_creates_with_en_for_other_locales() -> None:
    svc, repo, session = make_service()
    repo.get = AsyncMock(return_value=None)
    created = MagicMock(spec=UserSettings)
    created.language = "en"
    repo.get_or_create = AsyncMock(return_value=created)

    result = await svc.ensure_user_settings(user_id=42, language_code="fr-FR")

    assert result is created
    repo.get_or_create.assert_awaited_once_with(42, language="en")
    session.commit.assert_awaited_once()


async def test_ensure_user_settings_creates_with_en_when_language_code_missing() -> None:
    svc, repo, session = make_service()
    repo.get = AsyncMock(return_value=None)
    created = MagicMock(spec=UserSettings)
    created.language = "en"
    repo.get_or_create = AsyncMock(return_value=created)

    result = await svc.ensure_user_settings(user_id=42, language_code=None)

    assert result is created
    repo.get_or_create.assert_awaited_once_with(42, language="en")
    session.commit.assert_awaited_once()
