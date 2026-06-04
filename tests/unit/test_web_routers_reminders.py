"""Unit tests for web/routers/reminders.py — direct endpoint invocation for coverage.

These tests call the endpoint coroutines directly with mocked dependencies,
bypassing TestClient so that pytest-cov can trace every line regardless of
async/await suspension points.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from web.routers.reminders import (
    PatchReminderRequest,
    _compute_snooze_at,
    _get_item_preview,
    _make_response,
    list_reminders,
    patch_reminder,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

USER_ID = 111222333
FUTURE = datetime(2099, 1, 1, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_reminder(
    reminder_id: uuid.UUID | None = None,
    item_id: uuid.UUID | None = None,
    remind_at: datetime = FUTURE,
    snooze_count: int = 0,
    is_acknowledged: bool = False,
    is_cancelled: bool = False,
) -> MagicMock:
    """Build a mock Reminder ORM object."""
    r = MagicMock()
    r.id = reminder_id or uuid.uuid4()
    r.item_id = item_id or uuid.uuid4()
    r.remind_at = remind_at
    r.snooze_count = snooze_count
    r.is_acknowledged = is_acknowledged
    r.is_cancelled = is_cancelled
    return r


def _make_item(content: str = "task content") -> MagicMock:
    """Build a mock Item ORM object."""
    item = MagicMock()
    item.content = content
    return item


def _make_session() -> MagicMock:
    return MagicMock(spec=AsyncSession)


# ---------------------------------------------------------------------------
# _compute_snooze_at — pure function, no DB
# ---------------------------------------------------------------------------


def test_compute_snooze_at_plus1h_returns_one_hour_from_now() -> None:
    """_compute_snooze_at('+1h') returns approximately now + 1 hour."""
    before = datetime.now(UTC)
    result = _compute_snooze_at("+1h")
    after = datetime.now(UTC)
    assert before + timedelta(hours=1) <= result <= after + timedelta(hours=1, seconds=1)


def test_compute_snooze_at_plus24h_returns_24_hours_from_now() -> None:
    """_compute_snooze_at('+24h') returns approximately now + 24 hours."""
    before = datetime.now(UTC)
    result = _compute_snooze_at("+24h")
    after = datetime.now(UTC)
    assert before + timedelta(hours=24) <= result <= after + timedelta(hours=24, seconds=1)


def test_compute_snooze_at_next_day_returns_midnight_utc() -> None:
    """_compute_snooze_at('next_day') returns midnight UTC of tomorrow."""
    result = _compute_snooze_at("next_day")
    assert result.hour == 0
    assert result.minute == 0
    assert result.second == 0
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).date()
    assert result.date() == tomorrow


# ---------------------------------------------------------------------------
# _get_item_preview
# ---------------------------------------------------------------------------


async def test_get_item_preview_returns_truncated_content() -> None:
    """_get_item_preview returns up to 120 chars of item content."""
    item_id = uuid.uuid4()
    item_repo = MagicMock()
    item_repo.get_by_id = AsyncMock(return_value=_make_item("x" * 200))

    result = await _get_item_preview(item_repo, item_id)

    assert result == "x" * 120
    item_repo.get_by_id.assert_awaited_once_with(item_id)


async def test_get_item_preview_returns_empty_string_when_item_not_found() -> None:
    """_get_item_preview returns empty string when item_repo.get_by_id returns None."""
    item_repo = MagicMock()
    item_repo.get_by_id = AsyncMock(return_value=None)

    result = await _get_item_preview(item_repo, uuid.uuid4())

    assert result == ""


async def test_get_item_preview_returns_full_content_when_short() -> None:
    """_get_item_preview returns full content when content is under 120 chars."""
    item_repo = MagicMock()
    item_repo.get_by_id = AsyncMock(return_value=_make_item("short"))

    result = await _get_item_preview(item_repo, uuid.uuid4())

    assert result == "short"


# ---------------------------------------------------------------------------
# _make_response
# ---------------------------------------------------------------------------


def test_make_response_builds_correct_reminder_response() -> None:
    """_make_response converts a Reminder ORM object to ReminderResponse correctly."""
    r = _make_reminder(snooze_count=2)
    response = _make_response(r, "preview text")

    assert response.id == str(r.id)
    assert response.item_id == str(r.item_id)
    assert response.remind_at == r.remind_at.isoformat()
    assert response.snooze_count == 2
    assert response.item_preview == "preview text"


# ---------------------------------------------------------------------------
# list_reminders endpoint
# ---------------------------------------------------------------------------


async def test_list_reminders_returns_empty_list_when_no_upcoming() -> None:
    """list_reminders returns [] when get_upcoming returns no reminders."""
    session = _make_session()
    current_user = {"sub": str(USER_ID)}

    with (
        patch("web.routers.reminders.ReminderService") as MockSvc,
        patch("web.routers.reminders.ItemRepository"),
        patch("web.routers.reminders.ReminderRepository"),
    ):
        svc = MagicMock()
        svc.get_upcoming = AsyncMock(return_value=[])
        MockSvc.return_value = svc

        result = await list_reminders(current_user=current_user, session=session)

    assert result == []


async def test_list_reminders_returns_response_for_each_reminder() -> None:
    """list_reminders builds a ReminderResponse for each upcoming reminder."""
    session = _make_session()
    current_user = {"sub": str(USER_ID)}
    reminder1 = _make_reminder()
    reminder2 = _make_reminder()

    with (
        patch("web.routers.reminders.ReminderService") as MockSvc,
        patch("web.routers.reminders.ItemRepository") as MockItemRepo,
        patch("web.routers.reminders.ReminderRepository"),
    ):
        svc = MagicMock()
        svc.get_upcoming = AsyncMock(return_value=[reminder1, reminder2])
        MockSvc.return_value = svc

        item_repo = MagicMock()
        item_repo.get_by_id = AsyncMock(return_value=_make_item("content"))
        MockItemRepo.return_value = item_repo

        result = await list_reminders(current_user=current_user, session=session)

    assert len(result) == 2
    assert result[0].id == str(reminder1.id)
    assert result[1].id == str(reminder2.id)


async def test_list_reminders_truncates_item_preview_to_120_chars() -> None:
    """list_reminders truncates item_preview to 120 characters in each response."""
    session = _make_session()
    current_user = {"sub": str(USER_ID)}
    reminder = _make_reminder()

    with (
        patch("web.routers.reminders.ReminderService") as MockSvc,
        patch("web.routers.reminders.ItemRepository") as MockItemRepo,
        patch("web.routers.reminders.ReminderRepository"),
    ):
        svc = MagicMock()
        svc.get_upcoming = AsyncMock(return_value=[reminder])
        MockSvc.return_value = svc

        item_repo = MagicMock()
        item_repo.get_by_id = AsyncMock(return_value=_make_item("z" * 200))
        MockItemRepo.return_value = item_repo

        result = await list_reminders(current_user=current_user, session=session)

    assert len(result[0].item_preview) == 120


async def test_list_reminders_uses_correct_user_id() -> None:
    """list_reminders calls get_upcoming with the user_id from current_user['sub']."""
    session = _make_session()
    current_user = {"sub": "42"}

    with (
        patch("web.routers.reminders.ReminderService") as MockSvc,
        patch("web.routers.reminders.ItemRepository"),
        patch("web.routers.reminders.ReminderRepository"),
    ):
        svc = MagicMock()
        svc.get_upcoming = AsyncMock(return_value=[])
        MockSvc.return_value = svc

        await list_reminders(current_user=current_user, session=session)

    svc.get_upcoming.assert_awaited_once_with(42)


# ---------------------------------------------------------------------------
# patch_reminder endpoint — 400 / 404 validation paths
# ---------------------------------------------------------------------------


async def test_patch_reminder_invalid_uuid_raises_400() -> None:
    """patch_reminder raises HTTP 400 when reminder_id is not a valid UUID."""
    session = _make_session()
    current_user = {"sub": str(USER_ID)}
    body = PatchReminderRequest(action="acknowledge")

    with pytest.raises(HTTPException) as exc_info:
        await patch_reminder(
            reminder_id="not-a-uuid",
            body=body,
            current_user=current_user,
            session=session,
        )

    assert exc_info.value.status_code == 400


async def test_patch_reminder_unknown_action_raises_400() -> None:
    """patch_reminder raises HTTP 400 for an unknown action."""
    session = _make_session()
    current_user = {"sub": str(USER_ID)}
    body = PatchReminderRequest(action="explode")

    with pytest.raises(HTTPException) as exc_info:
        await patch_reminder(
            reminder_id=str(uuid.uuid4()),
            body=body,
            current_user=current_user,
            session=session,
        )

    assert exc_info.value.status_code == 400


async def test_patch_reminder_snooze_without_option_raises_400() -> None:
    """patch_reminder raises HTTP 400 when action='snooze' but snooze_option is None."""
    session = _make_session()
    current_user = {"sub": str(USER_ID)}
    body = PatchReminderRequest(action="snooze", snooze_option=None)

    with pytest.raises(HTTPException) as exc_info:
        await patch_reminder(
            reminder_id=str(uuid.uuid4()),
            body=body,
            current_user=current_user,
            session=session,
        )

    assert exc_info.value.status_code == 400


async def test_patch_reminder_snooze_invalid_option_raises_400() -> None:
    """patch_reminder raises HTTP 400 for snooze_option not in allowed set."""
    session = _make_session()
    current_user = {"sub": str(USER_ID)}
    body = PatchReminderRequest(action="snooze", snooze_option="+2h")

    with pytest.raises(HTTPException) as exc_info:
        await patch_reminder(
            reminder_id=str(uuid.uuid4()),
            body=body,
            current_user=current_user,
            session=session,
        )

    assert exc_info.value.status_code == 400


async def test_patch_reminder_not_found_raises_404() -> None:
    """patch_reminder raises HTTP 404 when the reminder does not exist for the user."""
    session = _make_session()
    current_user = {"sub": str(USER_ID)}
    body = PatchReminderRequest(action="acknowledge")

    with (
        patch("web.routers.reminders.ReminderService") as MockSvc,
        patch("web.routers.reminders.ItemRepository"),
        patch("web.routers.reminders.ReminderRepository"),
    ):
        svc = MagicMock()
        svc.get_by_id_for_user = AsyncMock(return_value=None)
        MockSvc.return_value = svc

        with pytest.raises(HTTPException) as exc_info:
            await patch_reminder(
                reminder_id=str(uuid.uuid4()),
                body=body,
                current_user=current_user,
                session=session,
            )

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# patch_reminder endpoint — acknowledge action
# ---------------------------------------------------------------------------


async def test_patch_reminder_acknowledge_calls_service_and_returns_response() -> None:
    """patch_reminder with action='acknowledge' calls svc.acknowledge and returns updated state."""
    session = _make_session()
    current_user = {"sub": str(USER_ID)}
    reminder_id = uuid.uuid4()
    reminder = _make_reminder(reminder_id=reminder_id)
    updated_reminder = _make_reminder(reminder_id=reminder_id, is_acknowledged=True)
    body = PatchReminderRequest(action="acknowledge")

    with (
        patch("web.routers.reminders.ReminderService") as MockSvc,
        patch("web.routers.reminders.ItemRepository") as MockItemRepo,
        patch("web.routers.reminders.ReminderRepository"),
    ):
        svc = MagicMock()
        svc.get_by_id_for_user = AsyncMock(side_effect=[reminder, updated_reminder])
        svc.acknowledge = AsyncMock()
        MockSvc.return_value = svc

        item_repo = MagicMock()
        item_repo.get_by_id = AsyncMock(return_value=_make_item("my task"))
        MockItemRepo.return_value = item_repo

        result = await patch_reminder(
            reminder_id=str(reminder_id),
            body=body,
            current_user=current_user,
            session=session,
        )

    svc.acknowledge.assert_awaited_once_with(reminder_id, USER_ID)
    assert result.id == str(reminder_id)
    assert result.item_preview == "my task"


# ---------------------------------------------------------------------------
# patch_reminder endpoint — cancel action
# ---------------------------------------------------------------------------


async def test_patch_reminder_cancel_calls_service_and_returns_response() -> None:
    """patch_reminder with action='cancel' calls svc.cancel_for_user and returns updated state."""
    session = _make_session()
    current_user = {"sub": str(USER_ID)}
    reminder_id = uuid.uuid4()
    reminder = _make_reminder(reminder_id=reminder_id)
    updated_reminder = _make_reminder(reminder_id=reminder_id, is_cancelled=True)
    body = PatchReminderRequest(action="cancel")

    with (
        patch("web.routers.reminders.ReminderService") as MockSvc,
        patch("web.routers.reminders.ItemRepository") as MockItemRepo,
        patch("web.routers.reminders.ReminderRepository"),
    ):
        svc = MagicMock()
        svc.get_by_id_for_user = AsyncMock(side_effect=[reminder, updated_reminder])
        svc.cancel_for_user = AsyncMock()
        MockSvc.return_value = svc

        item_repo = MagicMock()
        item_repo.get_by_id = AsyncMock(return_value=_make_item("cancel this"))
        MockItemRepo.return_value = item_repo

        result = await patch_reminder(
            reminder_id=str(reminder_id),
            body=body,
            current_user=current_user,
            session=session,
        )

    svc.cancel_for_user.assert_awaited_once_with(reminder_id, USER_ID)
    assert result.id == str(reminder_id)


# ---------------------------------------------------------------------------
# patch_reminder endpoint — snooze action
# ---------------------------------------------------------------------------


async def test_patch_reminder_snooze_calls_svc_snooze_with_computed_time() -> None:
    """patch_reminder with action='snooze' calls svc.snooze with the computed remind_at."""
    session = _make_session()
    current_user = {"sub": str(USER_ID)}
    reminder_id = uuid.uuid4()
    reminder = _make_reminder(reminder_id=reminder_id)
    updated_reminder = _make_reminder(reminder_id=reminder_id, snooze_count=1)
    body = PatchReminderRequest(action="snooze", snooze_option="+1h")

    with (
        patch("web.routers.reminders.ReminderService") as MockSvc,
        patch("web.routers.reminders.ItemRepository") as MockItemRepo,
        patch("web.routers.reminders.ReminderRepository"),
    ):
        svc = MagicMock()
        svc.get_by_id_for_user = AsyncMock(side_effect=[reminder, updated_reminder])
        svc.snooze = AsyncMock()
        MockSvc.return_value = svc

        item_repo = MagicMock()
        item_repo.get_by_id = AsyncMock(return_value=_make_item("snooze me"))
        MockItemRepo.return_value = item_repo

        before = datetime.now(UTC)
        result = await patch_reminder(
            reminder_id=str(reminder_id),
            body=body,
            current_user=current_user,
            session=session,
        )
        after = datetime.now(UTC)

    assert svc.snooze.await_count == 1
    call_args = svc.snooze.call_args
    snooze_time = call_args[0][2]
    assert before + timedelta(hours=1) <= snooze_time <= after + timedelta(hours=1, seconds=1)
    assert result.snooze_count == 1


async def test_patch_reminder_snooze_next_day_option_works() -> None:
    """patch_reminder with snooze_option='next_day' calls svc.snooze with midnight UTC."""
    session = _make_session()
    current_user = {"sub": str(USER_ID)}
    reminder_id = uuid.uuid4()
    reminder = _make_reminder(reminder_id=reminder_id)
    updated_reminder = _make_reminder(reminder_id=reminder_id, snooze_count=1)
    body = PatchReminderRequest(action="snooze", snooze_option="next_day")

    with (
        patch("web.routers.reminders.ReminderService") as MockSvc,
        patch("web.routers.reminders.ItemRepository") as MockItemRepo,
        patch("web.routers.reminders.ReminderRepository"),
    ):
        svc = MagicMock()
        svc.get_by_id_for_user = AsyncMock(side_effect=[reminder, updated_reminder])
        svc.snooze = AsyncMock()
        MockSvc.return_value = svc

        item_repo = MagicMock()
        item_repo.get_by_id = AsyncMock(return_value=_make_item("next day"))
        MockItemRepo.return_value = item_repo

        await patch_reminder(
            reminder_id=str(reminder_id),
            body=body,
            current_user=current_user,
            session=session,
        )

    snooze_time = svc.snooze.call_args[0][2]
    assert snooze_time.hour == 0
    assert snooze_time.minute == 0


# ---------------------------------------------------------------------------
# patch_reminder endpoint — defensive fallback (updated is None)
# ---------------------------------------------------------------------------


async def test_patch_reminder_returns_pre_action_snapshot_when_reload_returns_none() -> None:
    """patch_reminder falls back to pre-action snapshot when reload returns None."""
    session = _make_session()
    current_user = {"sub": str(USER_ID)}
    reminder_id = uuid.uuid4()
    reminder = _make_reminder(reminder_id=reminder_id)
    body = PatchReminderRequest(action="acknowledge")

    with (
        patch("web.routers.reminders.ReminderService") as MockSvc,
        patch("web.routers.reminders.ItemRepository") as MockItemRepo,
        patch("web.routers.reminders.ReminderRepository"),
    ):
        svc = MagicMock()
        # First call (ownership check) returns reminder; second call (reload) returns None.
        svc.get_by_id_for_user = AsyncMock(side_effect=[reminder, None])
        svc.acknowledge = AsyncMock()
        MockSvc.return_value = svc

        item_repo = MagicMock()
        item_repo.get_by_id = AsyncMock(return_value=_make_item("fallback content"))
        MockItemRepo.return_value = item_repo

        result = await patch_reminder(
            reminder_id=str(reminder_id),
            body=body,
            current_user=current_user,
            session=session,
        )

    assert result.id == str(reminder_id)
    assert result.item_preview == "fallback content"
