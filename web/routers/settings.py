"""Settings router — GET /api/settings and PATCH /api/settings."""

from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from bot.i18n import SUPPORTED_LANGUAGES
from bot.models.user_settings import UserSettings
from bot.repositories.user_settings import UserSettingsRepository
from web.dependencies import get_current_user, get_db_session

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Cache the available IANA timezone set at module load time — it is immutable.
_VALID_TIMEZONES: frozenset[str] = frozenset(available_timezones())


# ---------------------------------------------------------------------------
# Response / request schemas
# ---------------------------------------------------------------------------


class SettingsResponse(BaseModel):
    """User settings representation returned by GET and PATCH."""

    timezone: str
    language: str


class PatchSettingsRequest(BaseModel):
    """Request body for PATCH /api/settings — all fields optional."""

    timezone: str | None = None
    language: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings_to_response(settings: UserSettings) -> SettingsResponse:
    """Convert a UserSettings ORM object to SettingsResponse."""
    return SettingsResponse(timezone=settings.timezone, language=settings.language)


def _default_response() -> SettingsResponse:
    """Return SettingsResponse populated with model-level defaults."""
    return SettingsResponse(
        timezone=UserSettings.timezone.default.arg,  # type: ignore[union-attr]
        language=UserSettings.language.default.arg,  # type: ignore[union-attr]
    )


def _validate_timezone(tz: str) -> None:
    """Raise HTTP 422 when tz is not a valid IANA timezone string."""
    if tz not in _VALID_TIMEZONES:
        # Double-check with ZoneInfo to catch any edge cases not in available_timezones().
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid IANA timezone: {tz!r}",
            ) from exc


def _validate_language(lang: str) -> None:
    """Raise HTTP 422 when lang is not a supported locale."""
    if lang not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unsupported language: {lang!r}. "
                f"Must be one of: {', '.join(sorted(SUPPORTED_LANGUAGES))}"
            ),
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=SettingsResponse)
async def get_settings(
    current_user: Annotated[dict, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SettingsResponse:
    """Return the authenticated user's current settings, or model defaults if none exist.

    Returns HTTP 401 without a valid Bearer JWT.
    """
    user_id = int(current_user["sub"])
    repo = UserSettingsRepository(session)
    settings = await repo.get(user_id)
    if settings is None:
        return _default_response()
    return _settings_to_response(settings)


@router.patch("", response_model=SettingsResponse)
async def patch_settings(
    body: PatchSettingsRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SettingsResponse:
    """Partially update the authenticated user's settings and return the updated values.

    Validates timezone against IANA available_timezones() and language against the
    bot's supported locales. Returns HTTP 422 for invalid values.
    Returns HTTP 401 without a valid Bearer JWT.
    """
    if body.timezone is not None:
        _validate_timezone(body.timezone)
    if body.language is not None:
        _validate_language(body.language)

    user_id = int(current_user["sub"])
    repo = UserSettingsRepository(session)

    # Upsert each provided field individually so that omitted fields are untouched.
    if body.timezone is not None:
        await repo.set_timezone(user_id, body.timezone)
    if body.language is not None:
        await repo.set_language(user_id, body.language)

    # If neither field was provided, still ensure the row exists so we can return it.
    if body.timezone is None and body.language is None:
        await repo.get_or_create(user_id)

    await session.commit()

    settings = await repo.get(user_id)
    if settings is None:
        # Defensive: should not happen after upsert above.
        return _default_response()
    return _settings_to_response(settings)
