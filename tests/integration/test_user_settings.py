import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from bot.exceptions import InvalidTimezoneError
from bot.repositories.user_settings import UserSettingsRepository
from bot.services.user_settings_service import UserSettingsService


async def test_repo_get_returns_none_for_unknown_user(db_session: AsyncSession) -> None:
    repo = UserSettingsRepository(db_session)
    assert await repo.get(user_id=999) is None


async def test_repo_get_or_create_creates_with_default_utc(db_session: AsyncSession) -> None:
    repo = UserSettingsRepository(db_session)

    settings = await repo.get_or_create(user_id=42)
    await db_session.commit()

    assert settings.user_id == 42
    assert settings.timezone == "UTC"


async def test_repo_get_or_create_returns_existing(db_session: AsyncSession) -> None:
    repo = UserSettingsRepository(db_session)
    first = await repo.get_or_create(user_id=42)
    await db_session.commit()

    second = await repo.get_or_create(user_id=42)

    assert second.user_id == first.user_id
    assert second.timezone == first.timezone


async def test_repo_set_timezone_creates_row_when_missing(db_session: AsyncSession) -> None:
    repo = UserSettingsRepository(db_session)

    settings = await repo.set_timezone(user_id=42, tz_name="Europe/Moscow")
    await db_session.commit()

    assert settings.timezone == "Europe/Moscow"
    fetched = await repo.get(user_id=42)
    assert fetched is not None
    assert fetched.timezone == "Europe/Moscow"


async def test_repo_set_timezone_updates_existing_row(db_session: AsyncSession) -> None:
    repo = UserSettingsRepository(db_session)
    await repo.get_or_create(user_id=42)
    await db_session.commit()

    await repo.set_timezone(user_id=42, tz_name="Asia/Tokyo")
    await db_session.commit()

    fetched = await repo.get(user_id=42)
    assert fetched is not None
    assert fetched.timezone == "Asia/Tokyo"


async def test_service_get_timezone_returns_utc_when_no_row(db_session: AsyncSession) -> None:
    repo = UserSettingsRepository(db_session)
    svc = UserSettingsService(session=db_session, repo=repo)

    assert await svc.get_timezone(user_id=42) == "UTC"


async def test_service_set_then_get_round_trip(db_session: AsyncSession) -> None:
    repo = UserSettingsRepository(db_session)
    svc = UserSettingsService(session=db_session, repo=repo)

    await svc.set_timezone(user_id=42, tz_name="Europe/Moscow")

    assert await svc.get_timezone(user_id=42) == "Europe/Moscow"


async def test_service_set_timezone_overwrites(db_session: AsyncSession) -> None:
    repo = UserSettingsRepository(db_session)
    svc = UserSettingsService(session=db_session, repo=repo)

    await svc.set_timezone(user_id=42, tz_name="Europe/Moscow")
    await svc.set_timezone(user_id=42, tz_name="Asia/Tokyo")

    assert await svc.get_timezone(user_id=42) == "Asia/Tokyo"


async def test_service_set_timezone_invalid_does_not_persist(db_session: AsyncSession) -> None:
    repo = UserSettingsRepository(db_session)
    svc = UserSettingsService(session=db_session, repo=repo)

    with pytest.raises(InvalidTimezoneError):
        await svc.set_timezone(user_id=42, tz_name="Bogus/Zone")

    # No row should have been created
    assert await repo.get(user_id=42) is None


async def test_service_isolates_users(db_session: AsyncSession) -> None:
    repo = UserSettingsRepository(db_session)
    svc = UserSettingsService(session=db_session, repo=repo)

    await svc.set_timezone(user_id=1, tz_name="Europe/Moscow")
    await svc.set_timezone(user_id=2, tz_name="Asia/Tokyo")

    assert await svc.get_timezone(user_id=1) == "Europe/Moscow"
    assert await svc.get_timezone(user_id=2) == "Asia/Tokyo"
