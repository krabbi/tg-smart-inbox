"""Unit tests for web/routers/settings.py — direct endpoint invocation for coverage.

These tests call the endpoint coroutines directly with mocked dependencies,
bypassing TestClient so that pytest-cov can trace every line regardless of
async/await suspension points.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from web.routers.settings import (
    PatchSettingsRequest,
    SettingsResponse,
    _default_response,
    _settings_to_response,
    _validate_language,
    _validate_timezone,
    get_settings,
    patch_settings,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

USER_ID = 42


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session() -> MagicMock:
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    return session


def _make_settings(timezone: str = "UTC", language: str = "en") -> MagicMock:
    """Build a mock UserSettings ORM object."""
    s = MagicMock()
    s.timezone = timezone
    s.language = language
    return s


def _make_current_user(user_id: int = USER_ID) -> dict:
    return {"sub": str(user_id)}


# ---------------------------------------------------------------------------
# _default_response — pure helper
# ---------------------------------------------------------------------------


def test_default_response_returns_utc_and_en() -> None:
    """_default_response returns 'UTC' timezone and 'en' language."""
    result = _default_response()
    assert result.timezone == "UTC"
    assert result.language == "en"


# ---------------------------------------------------------------------------
# _settings_to_response — pure helper
# ---------------------------------------------------------------------------


def test_settings_to_response_maps_fields_correctly() -> None:
    """_settings_to_response correctly maps ORM fields to SettingsResponse."""
    settings = _make_settings(timezone="Europe/Moscow", language="ru")
    result = _settings_to_response(settings)
    assert result.timezone == "Europe/Moscow"
    assert result.language == "ru"


# ---------------------------------------------------------------------------
# _validate_timezone
# ---------------------------------------------------------------------------


def test_validate_timezone_accepts_valid_iana_name() -> None:
    """_validate_timezone does not raise for a well-known IANA timezone."""
    _validate_timezone("Europe/London")  # should not raise


def test_validate_timezone_accepts_utc() -> None:
    """_validate_timezone does not raise for 'UTC'."""
    _validate_timezone("UTC")  # should not raise


def test_validate_timezone_raises_422_for_unknown_zone() -> None:
    """_validate_timezone raises HTTP 422 for a non-existent timezone string."""
    with pytest.raises(HTTPException) as exc_info:
        _validate_timezone("Bogus/Zone")
    assert exc_info.value.status_code == 422
    assert "Bogus/Zone" in exc_info.value.detail


def test_validate_timezone_raises_422_for_empty_string() -> None:
    """_validate_timezone raises HTTP 422 for an empty string."""
    with pytest.raises(HTTPException) as exc_info:
        _validate_timezone("")
    assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# _validate_language
# ---------------------------------------------------------------------------


def test_validate_language_accepts_en() -> None:
    """_validate_language does not raise for 'en'."""
    _validate_language("en")  # should not raise


def test_validate_language_accepts_ru() -> None:
    """_validate_language does not raise for 'ru'."""
    _validate_language("ru")  # should not raise


def test_validate_language_raises_422_for_unsupported_code() -> None:
    """_validate_language raises HTTP 422 for an unsupported language code."""
    with pytest.raises(HTTPException) as exc_info:
        _validate_language("de")
    assert exc_info.value.status_code == 422
    assert "de" in exc_info.value.detail


def test_validate_language_raises_422_for_empty_string() -> None:
    """_validate_language raises HTTP 422 for an empty string."""
    with pytest.raises(HTTPException) as exc_info:
        _validate_language("")
    assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/settings — get_settings endpoint
# ---------------------------------------------------------------------------


async def test_get_settings_returns_stored_settings_when_row_exists() -> None:
    """get_settings returns the user's stored timezone and language."""
    session = _make_session()
    current_user = _make_current_user()
    stored = _make_settings(timezone="Asia/Tokyo", language="ru")

    with patch("web.routers.settings.UserSettingsRepository") as MockRepo:
        repo = MagicMock()
        repo.get = AsyncMock(return_value=stored)
        MockRepo.return_value = repo

        result = await get_settings(current_user=current_user, session=session)

    assert result.timezone == "Asia/Tokyo"
    assert result.language == "ru"
    repo.get.assert_awaited_once_with(USER_ID)


async def test_get_settings_returns_defaults_when_no_row_exists() -> None:
    """get_settings returns model defaults when no settings row exists for the user."""
    session = _make_session()
    current_user = _make_current_user()

    with patch("web.routers.settings.UserSettingsRepository") as MockRepo:
        repo = MagicMock()
        repo.get = AsyncMock(return_value=None)
        MockRepo.return_value = repo

        result = await get_settings(current_user=current_user, session=session)

    assert result.timezone == "UTC"
    assert result.language == "en"


async def test_get_settings_uses_correct_user_id() -> None:
    """get_settings passes the telegram_id from JWT claims to the repository."""
    session = _make_session()
    current_user = {"sub": "99"}

    with patch("web.routers.settings.UserSettingsRepository") as MockRepo:
        repo = MagicMock()
        repo.get = AsyncMock(return_value=_make_settings())
        MockRepo.return_value = repo

        await get_settings(current_user=current_user, session=session)

    repo.get.assert_awaited_once_with(99)


async def test_get_settings_returns_settings_response_schema() -> None:
    """get_settings return value is a SettingsResponse instance."""
    session = _make_session()
    current_user = _make_current_user()

    with patch("web.routers.settings.UserSettingsRepository") as MockRepo:
        repo = MagicMock()
        repo.get = AsyncMock(return_value=_make_settings())
        MockRepo.return_value = repo

        result = await get_settings(current_user=current_user, session=session)

    assert isinstance(result, SettingsResponse)


# ---------------------------------------------------------------------------
# PATCH /api/settings — patch_settings endpoint — validation
# ---------------------------------------------------------------------------


async def test_patch_settings_invalid_timezone_raises_422() -> None:
    """patch_settings raises HTTP 422 when the timezone is not a valid IANA name."""
    session = _make_session()
    current_user = _make_current_user()
    body = PatchSettingsRequest(timezone="Not/AZone")

    with pytest.raises(HTTPException) as exc_info:
        await patch_settings(body=body, current_user=current_user, session=session)

    assert exc_info.value.status_code == 422


async def test_patch_settings_invalid_language_raises_422() -> None:
    """patch_settings raises HTTP 422 when the language is not in the supported set."""
    session = _make_session()
    current_user = _make_current_user()
    body = PatchSettingsRequest(language="fr")

    with pytest.raises(HTTPException) as exc_info:
        await patch_settings(body=body, current_user=current_user, session=session)

    assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /api/settings — patch_settings endpoint — success paths
# ---------------------------------------------------------------------------


async def test_patch_settings_updates_timezone_only() -> None:
    """patch_settings with only timezone provided updates that field and returns updated row."""
    session = _make_session()
    current_user = _make_current_user()
    body = PatchSettingsRequest(timezone="Europe/London")
    updated = _make_settings(timezone="Europe/London", language="en")

    with patch("web.routers.settings.UserSettingsRepository") as MockRepo:
        repo = MagicMock()
        repo.set_timezone = AsyncMock()
        repo.get = AsyncMock(return_value=updated)
        MockRepo.return_value = repo

        result = await patch_settings(body=body, current_user=current_user, session=session)

    repo.set_timezone.assert_awaited_once_with(USER_ID, "Europe/London")
    assert result.timezone == "Europe/London"
    assert result.language == "en"
    session.commit.assert_awaited_once()


async def test_patch_settings_updates_language_only() -> None:
    """patch_settings with only language provided updates that field and returns updated row."""
    session = _make_session()
    current_user = _make_current_user()
    body = PatchSettingsRequest(language="ru")
    updated = _make_settings(timezone="UTC", language="ru")

    with patch("web.routers.settings.UserSettingsRepository") as MockRepo:
        repo = MagicMock()
        repo.set_language = AsyncMock()
        repo.get = AsyncMock(return_value=updated)
        MockRepo.return_value = repo

        result = await patch_settings(body=body, current_user=current_user, session=session)

    repo.set_language.assert_awaited_once_with(USER_ID, "ru")
    assert result.language == "ru"
    session.commit.assert_awaited_once()


async def test_patch_settings_updates_both_fields() -> None:
    """patch_settings with both fields provided calls both repo methods."""
    session = _make_session()
    current_user = _make_current_user()
    body = PatchSettingsRequest(timezone="America/New_York", language="ru")
    updated = _make_settings(timezone="America/New_York", language="ru")

    with patch("web.routers.settings.UserSettingsRepository") as MockRepo:
        repo = MagicMock()
        repo.set_timezone = AsyncMock()
        repo.set_language = AsyncMock()
        repo.get = AsyncMock(return_value=updated)
        MockRepo.return_value = repo

        result = await patch_settings(body=body, current_user=current_user, session=session)

    repo.set_timezone.assert_awaited_once_with(USER_ID, "America/New_York")
    repo.set_language.assert_awaited_once_with(USER_ID, "ru")
    assert result.timezone == "America/New_York"
    assert result.language == "ru"
    session.commit.assert_awaited_once()


async def test_patch_settings_empty_body_calls_get_or_create() -> None:
    """patch_settings with no fields provided ensures the row exists via get_or_create."""
    session = _make_session()
    current_user = _make_current_user()
    body = PatchSettingsRequest()
    existing = _make_settings()

    with patch("web.routers.settings.UserSettingsRepository") as MockRepo:
        repo = MagicMock()
        repo.get_or_create = AsyncMock(return_value=existing)
        repo.get = AsyncMock(return_value=existing)
        MockRepo.return_value = repo

        result = await patch_settings(body=body, current_user=current_user, session=session)

    repo.get_or_create.assert_awaited_once_with(USER_ID)
    session.commit.assert_awaited_once()
    assert isinstance(result, SettingsResponse)


async def test_patch_settings_does_not_call_set_timezone_when_not_provided() -> None:
    """patch_settings does not call repo.set_timezone when timezone is absent from body."""
    session = _make_session()
    current_user = _make_current_user()
    body = PatchSettingsRequest(language="ru")
    updated = _make_settings(language="ru")

    with patch("web.routers.settings.UserSettingsRepository") as MockRepo:
        repo = MagicMock()
        repo.set_timezone = AsyncMock()
        repo.set_language = AsyncMock()
        repo.get = AsyncMock(return_value=updated)
        MockRepo.return_value = repo

        await patch_settings(body=body, current_user=current_user, session=session)

    repo.set_timezone.assert_not_called()


async def test_patch_settings_does_not_call_set_language_when_not_provided() -> None:
    """patch_settings does not call repo.set_language when language is absent from body."""
    session = _make_session()
    current_user = _make_current_user()
    body = PatchSettingsRequest(timezone="UTC")
    updated = _make_settings()

    with patch("web.routers.settings.UserSettingsRepository") as MockRepo:
        repo = MagicMock()
        repo.set_timezone = AsyncMock()
        repo.set_language = AsyncMock()
        repo.get = AsyncMock(return_value=updated)
        MockRepo.return_value = repo

        await patch_settings(body=body, current_user=current_user, session=session)

    repo.set_language.assert_not_called()


async def test_patch_settings_returns_defaults_when_get_returns_none_after_upsert() -> None:
    """patch_settings falls back to model defaults when repo.get returns None after upsert."""
    session = _make_session()
    current_user = _make_current_user()
    body = PatchSettingsRequest(timezone="UTC")

    with patch("web.routers.settings.UserSettingsRepository") as MockRepo:
        repo = MagicMock()
        repo.set_timezone = AsyncMock()
        # Defensive branch: get returns None even after set_timezone was called.
        repo.get = AsyncMock(return_value=None)
        MockRepo.return_value = repo

        result = await patch_settings(body=body, current_user=current_user, session=session)

    assert result.timezone == "UTC"
    assert result.language == "en"


async def test_patch_settings_commits_session() -> None:
    """patch_settings always commits the session after a successful upsert."""
    session = _make_session()
    current_user = _make_current_user()
    body = PatchSettingsRequest(language="en")

    with patch("web.routers.settings.UserSettingsRepository") as MockRepo:
        repo = MagicMock()
        repo.set_language = AsyncMock()
        repo.get = AsyncMock(return_value=_make_settings())
        MockRepo.return_value = repo

        await patch_settings(body=body, current_user=current_user, session=session)

    session.commit.assert_awaited_once()
