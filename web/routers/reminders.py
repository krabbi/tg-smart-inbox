"""Reminders router — GET /api/reminders and PATCH /api/reminders/{id}."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from bot.repositories.item_repository import ItemRepository
from bot.repositories.reminder_repository import ReminderRepository
from bot.services.reminder_service import ReminderService
from web.dependencies import get_current_user, get_db_session

router = APIRouter(prefix="/api/reminders", tags=["reminders"])

# Valid snooze option literals accepted by the API.
_SNOOZE_OPTIONS: frozenset[str] = frozenset({"+1h", "+24h", "next_day"})


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ReminderResponse(BaseModel):
    """Single reminder representation returned by list and patch endpoints."""

    id: str
    item_id: str
    remind_at: str
    snooze_count: int
    item_preview: str


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class PatchReminderRequest(BaseModel):
    """Request body for PATCH /api/reminders/{id}."""

    action: str
    snooze_option: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_snooze_at(snooze_option: str) -> datetime:
    """Return the new remind_at datetime for a given snooze option.

    Options:
    - ``+1h``      — 1 hour from now (UTC)
    - ``+24h``     — 24 hours from now (UTC)
    - ``next_day`` — midnight UTC of the next calendar day
    """
    now = datetime.now(UTC)
    if snooze_option == "+1h":
        return now + timedelta(hours=1)
    if snooze_option == "+24h":
        return now + timedelta(hours=24)
    # next_day — midnight UTC of the next calendar day
    tomorrow = (now + timedelta(days=1)).date()
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=UTC)


def _make_response(reminder, item_preview: str) -> ReminderResponse:
    """Convert a Reminder ORM object and an item preview string to ReminderResponse."""
    return ReminderResponse(
        id=str(reminder.id),
        item_id=str(reminder.item_id),
        remind_at=reminder.remind_at.isoformat(),
        snooze_count=reminder.snooze_count,
        item_preview=item_preview,
    )


async def _get_item_preview(item_repo: ItemRepository, item_id: uuid.UUID) -> str:
    """Return up to 120 chars of the item's content, or empty string if item is gone."""
    item = await item_repo.get_by_id(item_id)
    return item.content[:120] if item is not None else ""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[ReminderResponse])
async def list_reminders(
    current_user: Annotated[dict, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[ReminderResponse]:
    """Return upcoming (unsent, non-cancelled) reminders for the authenticated user.

    Returns an empty list when there are no upcoming reminders.
    Times are UTC ISO8601; the frontend applies user timezone for display.
    """
    user_id = int(current_user["sub"])
    item_repo = ItemRepository(session)
    svc = ReminderService(
        session=session,
        repo=ReminderRepository(session),
        item_repo=item_repo,
    )
    reminders = await svc.get_upcoming(user_id)

    result: list[ReminderResponse] = []
    for reminder in reminders:
        preview = await _get_item_preview(item_repo, reminder.item_id)
        result.append(_make_response(reminder, preview))
    return result


@router.patch("/{reminder_id}", response_model=ReminderResponse)
async def patch_reminder(
    reminder_id: str,
    body: PatchReminderRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReminderResponse:
    """Acknowledge, cancel, or snooze a reminder owned by the authenticated user.

    Returns HTTP 400 for unknown action or invalid snooze_option.
    Returns HTTP 400 when action is 'snooze' and snooze_option is missing.
    Returns HTTP 404 if the reminder does not exist or belongs to another user.
    """
    try:
        parsed_id = uuid.UUID(reminder_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid reminder id") from exc

    action = body.action
    if action not in {"acknowledge", "cancel", "snooze"}:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action '{action}'. Must be one of: acknowledge, cancel, snooze",
        )

    if action == "snooze":
        snooze_option = body.snooze_option
        if snooze_option is None:
            raise HTTPException(
                status_code=400,
                detail="snooze_option is required when action is 'snooze'",
            )
        if snooze_option not in _SNOOZE_OPTIONS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid snooze_option '{snooze_option}'. Must be one of: +1h, +24h, next_day"
                ),
            )

    user_id = int(current_user["sub"])
    item_repo = ItemRepository(session)
    svc = ReminderService(
        session=session,
        repo=ReminderRepository(session),
        item_repo=item_repo,
    )

    # Verify ownership before acting.
    reminder = await svc.get_by_id_for_user(parsed_id, user_id)
    if reminder is None:
        raise HTTPException(status_code=404, detail="Reminder not found")

    if action == "acknowledge":
        await svc.acknowledge(parsed_id, user_id)
    elif action == "cancel":
        await svc.cancel_for_user(parsed_id, user_id)
    else:
        # action == "snooze"; snooze_option already validated above.
        remind_at = _compute_snooze_at(body.snooze_option)  # type: ignore[arg-type]
        await svc.snooze(parsed_id, user_id, remind_at)

    # Reload the reminder after mutation for an accurate response.
    # get_by_id_for_user has no state filter so it works for ack/cancelled reminders too.
    updated = await svc.get_by_id_for_user(parsed_id, user_id)
    if updated is None:
        # Defensive: should not happen but fall back to pre-action snapshot.
        preview = await _get_item_preview(item_repo, reminder.item_id)
        return _make_response(reminder, preview)

    preview = await _get_item_preview(item_repo, updated.item_id)
    return _make_response(updated, preview)
