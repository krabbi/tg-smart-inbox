"""Integration tests for web/routers/reminders.py — GET /api/reminders and PATCH /api/reminders/{id}."""

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import NamedTuple
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import Config
from bot.models.base import Base
from bot.models.item import Item, ItemType
from bot.models.reminder import Reminder
from bot.repositories.reminder_repository import ReminderRepository
from web.main import create_app

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

JWT_SECRET = "test-super-secret-key-for-reminders-integration"
USER_ID = 111222333
OTHER_USER_ID = 999888777

# A fixed future time so reminders are "upcoming" (not sent / not cancelled).
FUTURE = datetime(2099, 1, 1, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fixtures — infrastructure
# ---------------------------------------------------------------------------


@pytest.fixture
def web_config() -> Config:
    """Minimal Config with JWT_SECRET set."""
    return Config(
        telegram_bot_token="1234567890:AAFakeTokenForTestingPurposesOnly",
        anthropic_api_key="sk-ant-fake",
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret=JWT_SECRET,
        allowed_user_ids=[],
    )


@pytest_asyncio.fixture
async def db_engine():
    """Create an in-memory SQLite engine with schema applied."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession backed by the in-memory SQLite engine."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def app_with_db(web_config: Config, db_session: AsyncSession) -> FastAPI:
    """FastAPI app with overridden DB session and fake current user (USER_ID)."""
    from web.dependencies import get_current_user, get_db_session

    with patch("web.main.init_db"):
        test_app = create_app(web_config)

    async def override_db_session() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    async def override_current_user() -> dict:
        return {"sub": str(USER_ID)}

    test_app.dependency_overrides[get_db_session] = override_db_session
    test_app.dependency_overrides[get_current_user] = override_current_user
    return test_app


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _create_item(session: AsyncSession, user_id: int, content: str) -> Item:
    """Insert a task Item for user_id and flush."""
    item = Item(user_id=user_id, type=ItemType.task, content=content)
    session.add(item)
    await session.flush()
    return item


async def _create_reminder(
    session: AsyncSession,
    item: Item,
    remind_at: datetime = FUTURE,
    *,
    is_sent: bool = False,
    is_cancelled: bool = False,
) -> Reminder:
    """Insert a Reminder for item and flush."""
    repo = ReminderRepository(session)
    reminder = await repo.create(item_id=item.id, remind_at=remind_at)
    if is_sent:
        reminder.is_sent = True
        await session.flush()
    if is_cancelled:
        reminder.is_cancelled = True
        await session.flush()
    return reminder


# ---------------------------------------------------------------------------
# Fixtures — seeded apps
# ---------------------------------------------------------------------------


class SeededData(NamedTuple):
    """Holds references to seeded ORM objects for tests that need them."""

    app: FastAPI
    reminder_id: uuid.UUID
    item_id: uuid.UUID
    other_reminder_id: uuid.UUID


@pytest_asyncio.fixture
async def seeded_app(app_with_db: FastAPI, db_session: AsyncSession) -> FastAPI:
    """App with one upcoming reminder for USER_ID and one for OTHER_USER_ID."""
    own_item = await _create_item(db_session, USER_ID, "buy milk")
    other_item = await _create_item(db_session, OTHER_USER_ID, "their task")
    await _create_reminder(db_session, own_item)
    await _create_reminder(db_session, other_item)
    await db_session.commit()
    return app_with_db


@pytest_asyncio.fixture
async def sent_reminder_app(app_with_db: FastAPI, db_session: AsyncSession) -> FastAPI:
    """App with one sent reminder for USER_ID."""
    item = await _create_item(db_session, USER_ID, "sent task")
    await _create_reminder(db_session, item, is_sent=True)
    await db_session.commit()
    return app_with_db


@pytest_asyncio.fixture
async def cancelled_reminder_app(app_with_db: FastAPI, db_session: AsyncSession) -> FastAPI:
    """App with one cancelled reminder for USER_ID."""
    item = await _create_item(db_session, USER_ID, "cancelled task")
    await _create_reminder(db_session, item, is_cancelled=True)
    await db_session.commit()
    return app_with_db


@pytest_asyncio.fixture
async def two_reminders_app(app_with_db: FastAPI, db_session: AsyncSession) -> FastAPI:
    """App with two reminders at different times for USER_ID (for ordering tests)."""
    item = await _create_item(db_session, USER_ID, "task")
    t1 = datetime(2099, 6, 1, tzinfo=UTC)
    t2 = datetime(2099, 1, 1, tzinfo=UTC)
    await _create_reminder(db_session, item, remind_at=t1)
    await _create_reminder(db_session, item, remind_at=t2)
    await db_session.commit()
    return app_with_db


@pytest_asyncio.fixture
async def long_content_app(app_with_db: FastAPI, db_session: AsyncSession) -> FastAPI:
    """App with a reminder whose item content is 200 chars (tests truncation)."""
    long_content = "x" * 200
    item = await _create_item(db_session, USER_ID, long_content)
    await _create_reminder(db_session, item)
    await db_session.commit()
    return app_with_db


@pytest_asyncio.fixture
async def seeded_app_with_data(
    app_with_db: FastAPI, db_session: AsyncSession
) -> SeededData:
    """App seeded with one own reminder; returns SeededData for tests needing reminder IDs."""
    own_item = await _create_item(db_session, USER_ID, "acknowledge me")
    other_item = await _create_item(db_session, OTHER_USER_ID, "not yours")
    own_reminder = await _create_reminder(db_session, own_item)
    other_reminder = await _create_reminder(db_session, other_item)
    await db_session.commit()
    return SeededData(
        app=app_with_db,
        reminder_id=own_reminder.id,
        item_id=own_item.id,
        other_reminder_id=other_reminder.id,
    )


# ---------------------------------------------------------------------------
# GET /api/reminders — no auth
# ---------------------------------------------------------------------------


def test_list_reminders_without_token_returns_401(web_config: Config) -> None:
    """GET /api/reminders without Authorization header returns HTTP 401."""
    with patch("web.main.init_db"):
        bare_app = create_app(web_config)
    with TestClient(bare_app, raise_server_exceptions=True) as client:
        response = client.get("/api/reminders")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/reminders — list
# ---------------------------------------------------------------------------


def test_list_reminders_empty_returns_empty_list(app_with_db: FastAPI) -> None:
    """GET /api/reminders with no reminders returns an empty list, not 404."""
    with TestClient(app_with_db, raise_server_exceptions=True) as client:
        response = client.get("/api/reminders")
    assert response.status_code == 200
    assert response.json() == []


def test_list_reminders_returns_upcoming_for_user(seeded_app: FastAPI) -> None:
    """GET /api/reminders returns upcoming reminders for the authenticated user."""
    with TestClient(seeded_app, raise_server_exceptions=True) as client:
        response = client.get("/api/reminders")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    r = data[0]
    assert "id" in r
    assert "item_id" in r
    assert "remind_at" in r
    assert "snooze_count" in r
    assert "item_preview" in r
    assert r["item_preview"] == "buy milk"
    assert r["snooze_count"] == 0


def test_list_reminders_excludes_sent_reminders(sent_reminder_app: FastAPI) -> None:
    """GET /api/reminders does not return reminders marked as sent."""
    with TestClient(sent_reminder_app, raise_server_exceptions=True) as client:
        response = client.get("/api/reminders")
    assert response.status_code == 200
    assert response.json() == []


def test_list_reminders_excludes_cancelled_reminders(cancelled_reminder_app: FastAPI) -> None:
    """GET /api/reminders does not return cancelled reminders."""
    with TestClient(cancelled_reminder_app, raise_server_exceptions=True) as client:
        response = client.get("/api/reminders")
    assert response.status_code == 200
    assert response.json() == []


def test_list_reminders_scoped_to_authenticated_user(seeded_app: FastAPI) -> None:
    """GET /api/reminders never returns another user's reminders."""
    with TestClient(seeded_app, raise_server_exceptions=True) as client:
        response = client.get("/api/reminders")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["item_preview"] == "buy milk"


def test_list_reminders_ordered_soonest_first(two_reminders_app: FastAPI) -> None:
    """GET /api/reminders returns reminders ordered soonest first."""
    with TestClient(two_reminders_app, raise_server_exceptions=True) as client:
        response = client.get("/api/reminders")
    data = response.json()
    assert len(data) == 2
    # t2 (Jan) should come before t1 (Jun)
    assert data[0]["remind_at"] < data[1]["remind_at"]


def test_list_reminders_item_preview_truncated_at_120_chars(long_content_app: FastAPI) -> None:
    """GET /api/reminders truncates item_preview to 120 characters."""
    with TestClient(long_content_app, raise_server_exceptions=True) as client:
        response = client.get("/api/reminders")
    data = response.json()
    assert len(data[0]["item_preview"]) == 120


# ---------------------------------------------------------------------------
# PATCH /api/reminders/{id} — no auth
# ---------------------------------------------------------------------------


def test_patch_reminder_without_token_returns_401(web_config: Config) -> None:
    """PATCH /api/reminders/{id} without Authorization header returns HTTP 401."""
    with patch("web.main.init_db"):
        bare_app = create_app(web_config)
    with TestClient(bare_app, raise_server_exceptions=True) as client:
        response = client.patch(f"/api/reminders/{uuid.uuid4()}", json={"action": "acknowledge"})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# PATCH /api/reminders/{id} — acknowledge
# ---------------------------------------------------------------------------


def test_patch_acknowledge_returns_200(seeded_app_with_data: SeededData) -> None:
    """PATCH acknowledge returns HTTP 200 with reminder data."""
    with TestClient(seeded_app_with_data.app, raise_server_exceptions=True) as client:
        response = client.patch(
            f"/api/reminders/{seeded_app_with_data.reminder_id}",
            json={"action": "acknowledge"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(seeded_app_with_data.reminder_id)
    assert data["item_preview"] == "acknowledge me"


async def test_patch_acknowledge_sets_is_acknowledged(
    seeded_app_with_data: SeededData, db_session: AsyncSession
) -> None:
    """PATCH acknowledge marks the reminder as acknowledged in the DB."""
    with TestClient(seeded_app_with_data.app, raise_server_exceptions=True) as client:
        client.patch(
            f"/api/reminders/{seeded_app_with_data.reminder_id}",
            json={"action": "acknowledge"},
        )

    repo = ReminderRepository(db_session)
    reminder = await repo.get_by_id_for_user(seeded_app_with_data.reminder_id, USER_ID)
    assert reminder is not None
    assert reminder.is_acknowledged is True


# ---------------------------------------------------------------------------
# PATCH /api/reminders/{id} — cancel
# ---------------------------------------------------------------------------


def test_patch_cancel_returns_200(seeded_app_with_data: SeededData) -> None:
    """PATCH cancel returns HTTP 200 with reminder data."""
    with TestClient(seeded_app_with_data.app, raise_server_exceptions=True) as client:
        response = client.patch(
            f"/api/reminders/{seeded_app_with_data.reminder_id}",
            json={"action": "cancel"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(seeded_app_with_data.reminder_id)


async def test_patch_cancel_sets_is_cancelled(
    seeded_app_with_data: SeededData, db_session: AsyncSession
) -> None:
    """PATCH cancel marks the reminder as cancelled in the DB."""
    with TestClient(seeded_app_with_data.app, raise_server_exceptions=True) as client:
        client.patch(
            f"/api/reminders/{seeded_app_with_data.reminder_id}",
            json={"action": "cancel"},
        )

    repo = ReminderRepository(db_session)
    reminder = await repo.get_by_id_for_user(seeded_app_with_data.reminder_id, USER_ID)
    assert reminder is not None
    assert reminder.is_cancelled is True


# ---------------------------------------------------------------------------
# PATCH /api/reminders/{id} — snooze
# ---------------------------------------------------------------------------


def test_patch_snooze_plus1h_returns_200(seeded_app_with_data: SeededData) -> None:
    """PATCH snooze with +1h returns HTTP 200."""
    with TestClient(seeded_app_with_data.app, raise_server_exceptions=True) as client:
        response = client.patch(
            f"/api/reminders/{seeded_app_with_data.reminder_id}",
            json={"action": "snooze", "snooze_option": "+1h"},
        )
    assert response.status_code == 200


def test_patch_snooze_plus24h_returns_200(seeded_app_with_data: SeededData) -> None:
    """PATCH snooze with +24h returns HTTP 200."""
    with TestClient(seeded_app_with_data.app, raise_server_exceptions=True) as client:
        response = client.patch(
            f"/api/reminders/{seeded_app_with_data.reminder_id}",
            json={"action": "snooze", "snooze_option": "+24h"},
        )
    assert response.status_code == 200


def test_patch_snooze_next_day_returns_200(seeded_app_with_data: SeededData) -> None:
    """PATCH snooze with next_day returns HTTP 200."""
    with TestClient(seeded_app_with_data.app, raise_server_exceptions=True) as client:
        response = client.patch(
            f"/api/reminders/{seeded_app_with_data.reminder_id}",
            json={"action": "snooze", "snooze_option": "next_day"},
        )
    assert response.status_code == 200


async def test_patch_snooze_acknowledges_original_and_creates_new(
    seeded_app_with_data: SeededData, db_session: AsyncSession
) -> None:
    """PATCH snooze marks original as acknowledged and a new reminder appears in upcoming."""
    reminder_id = seeded_app_with_data.reminder_id

    with TestClient(seeded_app_with_data.app, raise_server_exceptions=True) as client:
        client.patch(
            f"/api/reminders/{reminder_id}",
            json={"action": "snooze", "snooze_option": "+1h"},
        )

    repo = ReminderRepository(db_session)
    original = await repo.get_by_id_for_user(reminder_id, USER_ID)
    assert original is not None
    assert original.is_acknowledged is True

    # A new snoozed reminder for the same item should exist.
    upcoming = await repo.get_upcoming(USER_ID)
    snoozed = [r for r in upcoming if r.snooze_count == 1]
    assert len(snoozed) == 1
    assert snoozed[0].item_id == seeded_app_with_data.item_id


# ---------------------------------------------------------------------------
# PATCH /api/reminders/{id} — 400 error cases
# ---------------------------------------------------------------------------


def test_patch_unknown_action_returns_400(app_with_db: FastAPI) -> None:
    """PATCH with an unknown action returns HTTP 400."""
    with TestClient(app_with_db, raise_server_exceptions=True) as client:
        response = client.patch(f"/api/reminders/{uuid.uuid4()}", json={"action": "invalidaction"})
    assert response.status_code == 400


def test_patch_snooze_without_snooze_option_returns_400(app_with_db: FastAPI) -> None:
    """PATCH snooze without snooze_option returns HTTP 400."""
    with TestClient(app_with_db, raise_server_exceptions=True) as client:
        response = client.patch(f"/api/reminders/{uuid.uuid4()}", json={"action": "snooze"})
    assert response.status_code == 400


def test_patch_snooze_with_free_text_snooze_option_returns_400(
    app_with_db: FastAPI,
) -> None:
    """PATCH snooze with a free-text snooze_option (not in allowed list) returns HTTP 400."""
    with TestClient(app_with_db, raise_server_exceptions=True) as client:
        response = client.patch(
            f"/api/reminders/{uuid.uuid4()}",
            json={"action": "snooze", "snooze_option": "tomorrow morning"},
        )
    assert response.status_code == 400


def test_patch_snooze_with_invalid_snooze_option_returns_400(
    app_with_db: FastAPI,
) -> None:
    """PATCH snooze with an unrecognised snooze_option returns HTTP 400."""
    with TestClient(app_with_db, raise_server_exceptions=True) as client:
        response = client.patch(
            f"/api/reminders/{uuid.uuid4()}",
            json={"action": "snooze", "snooze_option": "+2h"},
        )
    assert response.status_code == 400


def test_patch_invalid_uuid_returns_400(app_with_db: FastAPI) -> None:
    """PATCH /api/reminders/{id} with a non-UUID id returns HTTP 400."""
    with TestClient(app_with_db, raise_server_exceptions=True) as client:
        response = client.patch("/api/reminders/not-a-uuid", json={"action": "acknowledge"})
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# PATCH /api/reminders/{id} — 404 error cases
# ---------------------------------------------------------------------------


def test_patch_nonexistent_reminder_returns_404(app_with_db: FastAPI) -> None:
    """PATCH on a non-existent reminder id returns HTTP 404."""
    with TestClient(app_with_db, raise_server_exceptions=True) as client:
        response = client.patch(f"/api/reminders/{uuid.uuid4()}", json={"action": "acknowledge"})
    assert response.status_code == 404


def test_patch_other_users_reminder_returns_404(seeded_app_with_data: SeededData) -> None:
    """PATCH on another user's reminder returns HTTP 404."""
    with TestClient(seeded_app_with_data.app, raise_server_exceptions=True) as client:
        response = client.patch(
            f"/api/reminders/{seeded_app_with_data.other_reminder_id}",
            json={"action": "acknowledge"},
        )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Router registration
# ---------------------------------------------------------------------------


def test_create_app_registers_reminders_list_route(web_config: Config) -> None:
    """The /api/reminders route is registered on the app."""
    with patch("web.main.init_db"):
        test_app = create_app(web_config)
    routes = {route.path for route in test_app.routes}  # type: ignore[attr-defined]
    assert "/api/reminders" in routes


def test_create_app_registers_reminders_patch_route(web_config: Config) -> None:
    """The /api/reminders/{reminder_id} route is registered on the app."""
    with patch("web.main.init_db"):
        test_app = create_app(web_config)
    routes = {route.path for route in test_app.routes}  # type: ignore[attr-defined]
    assert "/api/reminders/{reminder_id}" in routes
