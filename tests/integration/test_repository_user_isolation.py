"""Cross-user data isolation guarantees for every repository.

These tests create rows for two distinct ``user_id`` values and verify that the
user-scoped repository methods (``get_*``, ``count_*``, ``search``,
``update_*_for_user``, ``cancel`` after ownership check, etc.) never return or
mutate data that belongs to a different user. They are the long-lived contract
backing the audit performed in issue #139.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.idea import Idea
from bot.models.item import Item, ItemType
from bot.models.reminder import Reminder
from bot.repositories.idea_repository import IdeaRepository
from bot.repositories.item_repository import ItemRepository
from bot.repositories.reminder_repository import ReminderRepository
from bot.repositories.user_settings import UserSettingsRepository
from bot.services.reminder_service import ReminderService

USER_A = 1001
USER_B = 2002


# --- ItemRepository ---------------------------------------------------------


async def test_items_get_by_user_only_returns_owned(db_session: AsyncSession) -> None:
    repo = ItemRepository(db_session)
    await repo.create(user_id=USER_A, type=ItemType.note, content="A note")
    await repo.create(user_id=USER_B, type=ItemType.note, content="B note")
    await db_session.commit()

    rows_a = await repo.get_by_user(USER_A)
    rows_b = await repo.get_by_user(USER_B)

    assert {it.user_id for it in rows_a} == {USER_A}
    assert {it.user_id for it in rows_b} == {USER_B}


async def test_items_get_recent_only_returns_owned(db_session: AsyncSession) -> None:
    repo = ItemRepository(db_session)
    await repo.create(user_id=USER_A, type=ItemType.note, content="A1")
    await repo.create(user_id=USER_B, type=ItemType.note, content="B1")
    await repo.create(user_id=USER_B, type=ItemType.note, content="B2")
    await db_session.commit()

    rows_a = await repo.get_recent(USER_A, limit=10, offset=0)
    rows_b = await repo.get_recent(USER_B, limit=10, offset=0)

    assert {it.user_id for it in rows_a} == {USER_A}
    assert {it.user_id for it in rows_b} == {USER_B}
    assert len(rows_a) == 1
    assert len(rows_b) == 2


async def test_items_count_by_user_only_counts_owned(db_session: AsyncSession) -> None:
    repo = ItemRepository(db_session)
    await repo.create(user_id=USER_A, type=ItemType.note, content="A1")
    await repo.create(user_id=USER_B, type=ItemType.note, content="B1")
    await repo.create(user_id=USER_B, type=ItemType.note, content="B2")
    await db_session.commit()

    assert await repo.count_by_user(USER_A) == 1
    assert await repo.count_by_user(USER_B) == 2


async def test_items_get_recent_by_type_isolation(db_session: AsyncSession) -> None:
    repo = ItemRepository(db_session)
    await repo.create(user_id=USER_A, type=ItemType.task, content="A task")
    await repo.create(user_id=USER_B, type=ItemType.task, content="B task")
    await db_session.commit()

    rows = await repo.get_recent_by_type(USER_A, ItemType.task, limit=10, offset=0)
    assert len(rows) == 1
    assert rows[0].user_id == USER_A
    assert rows[0].content == "A task"


async def test_items_count_by_user_and_type_isolation(db_session: AsyncSession) -> None:
    repo = ItemRepository(db_session)
    await repo.create(user_id=USER_A, type=ItemType.task, content="A task")
    await repo.create(user_id=USER_B, type=ItemType.task, content="B task 1")
    await repo.create(user_id=USER_B, type=ItemType.task, content="B task 2")
    await db_session.commit()

    assert await repo.count_by_user_and_type(USER_A, ItemType.task) == 1
    assert await repo.count_by_user_and_type(USER_B, ItemType.task) == 2


async def test_items_search_only_returns_owned(db_session: AsyncSession) -> None:
    repo = ItemRepository(db_session)
    await repo.create(user_id=USER_A, type=ItemType.note, content="meeting notes")
    await repo.create(user_id=USER_B, type=ItemType.note, content="meeting summary")
    await db_session.commit()

    results = await repo.search(USER_A, "meeting")
    assert len(results) == 1
    assert results[0].user_id == USER_A


async def test_items_get_by_id_for_user_returns_none_for_foreign_owner(
    db_session: AsyncSession,
) -> None:
    repo = ItemRepository(db_session)
    item = await repo.create(user_id=USER_A, type=ItemType.note, content="secret")
    await db_session.commit()

    # Owner sees the row.
    assert await repo.get_by_id_for_user(item.id, USER_A) is not None
    # Other user does not.
    assert await repo.get_by_id_for_user(item.id, USER_B) is None


async def test_items_update_scraped_text_for_user_refuses_foreign_writes(
    db_session: AsyncSession,
) -> None:
    repo = ItemRepository(db_session)
    item = await repo.create(user_id=USER_A, type=ItemType.link, content="https://x.test")
    await db_session.commit()

    # USER_B should not be able to overwrite USER_A's cache.
    ok = await repo.update_scraped_text_for_user(item.id, USER_B, "attacker payload")
    await db_session.commit()
    assert ok is False

    stored = await repo.get_by_id_for_user(item.id, USER_A)
    assert stored is not None
    assert stored.scraped_text is None


async def test_items_update_scraped_text_for_user_persists_owner_writes(
    db_session: AsyncSession,
) -> None:
    repo = ItemRepository(db_session)
    item = await repo.create(user_id=USER_A, type=ItemType.link, content="https://x.test")
    await db_session.commit()

    ok = await repo.update_scraped_text_for_user(item.id, USER_A, "page body")
    await db_session.commit()
    assert ok is True

    stored = await repo.get_by_id_for_user(item.id, USER_A)
    assert stored is not None
    assert stored.scraped_text == "page body"


# --- IdeaRepository ---------------------------------------------------------


async def test_ideas_get_all_only_returns_owned(db_session: AsyncSession) -> None:
    item_repo = ItemRepository(db_session)
    idea_repo = IdeaRepository(db_session)

    item_a = await item_repo.create(user_id=USER_A, type=ItemType.idea, content="A idea")
    await idea_repo.save(item_id=item_a.id, tags=["a"])
    item_b = await item_repo.create(user_id=USER_B, type=ItemType.idea, content="B idea")
    await idea_repo.save(item_id=item_b.id, tags=["b"])
    await db_session.commit()

    rows = await idea_repo.get_all(USER_A)
    assert len(rows) == 1
    assert rows[0][0].user_id == USER_A
    assert rows[0][0].content == "A idea"


async def test_ideas_get_page_only_returns_owned(db_session: AsyncSession) -> None:
    item_repo = ItemRepository(db_session)
    idea_repo = IdeaRepository(db_session)

    for i in range(3):
        item = await item_repo.create(user_id=USER_A, type=ItemType.idea, content=f"A{i}")
        await idea_repo.save(item_id=item.id, tags=[])
    item_b = await item_repo.create(user_id=USER_B, type=ItemType.idea, content="B")
    await idea_repo.save(item_id=item_b.id, tags=[])
    await db_session.commit()

    rows = await idea_repo.get_page(USER_A, limit=10, offset=0)
    assert len(rows) == 3
    assert all(item.user_id == USER_A for item, _ in rows)


async def test_ideas_count_by_user_isolation(db_session: AsyncSession) -> None:
    item_repo = ItemRepository(db_session)
    idea_repo = IdeaRepository(db_session)

    for _ in range(3):
        item = await item_repo.create(user_id=USER_A, type=ItemType.idea, content="A")
        await idea_repo.save(item_id=item.id, tags=[])
    item_b = await item_repo.create(user_id=USER_B, type=ItemType.idea, content="B")
    await idea_repo.save(item_id=item_b.id, tags=[])
    await db_session.commit()

    assert await idea_repo.count_by_user(USER_A) == 3
    assert await idea_repo.count_by_user(USER_B) == 1


# --- ReminderRepository -----------------------------------------------------


async def test_reminders_get_upcoming_only_returns_owned(db_session: AsyncSession) -> None:
    item_repo = ItemRepository(db_session)
    rem_repo = ReminderRepository(db_session)

    item_a = await item_repo.create(user_id=USER_A, type=ItemType.task, content="A task")
    item_b = await item_repo.create(user_id=USER_B, type=ItemType.task, content="B task")
    await db_session.commit()

    rem_a = await rem_repo.create(item_id=item_a.id, remind_at=datetime(2030, 1, 1, tzinfo=UTC))
    rem_b = await rem_repo.create(item_id=item_b.id, remind_at=datetime(2030, 1, 2, tzinfo=UTC))
    await db_session.commit()

    rows_a = await rem_repo.get_upcoming(USER_A)
    rows_b = await rem_repo.get_upcoming(USER_B)

    assert [r.id for r in rows_a] == [rem_a.id]
    assert [r.id for r in rows_b] == [rem_b.id]


async def test_reminders_get_by_id_for_user_returns_none_for_foreign_owner(
    db_session: AsyncSession,
) -> None:
    item_repo = ItemRepository(db_session)
    rem_repo = ReminderRepository(db_session)

    item_a = await item_repo.create(user_id=USER_A, type=ItemType.task, content="A task")
    await db_session.commit()
    rem_a = await rem_repo.create(item_id=item_a.id, remind_at=datetime(2030, 1, 1, tzinfo=UTC))
    await db_session.commit()

    assert await rem_repo.get_by_id_for_user(rem_a.id, USER_A) is not None
    assert await rem_repo.get_by_id_for_user(rem_a.id, USER_B) is None


async def test_reminder_service_cancel_for_user_refuses_foreign_owner(
    db_session: AsyncSession,
) -> None:
    item_repo = ItemRepository(db_session)
    rem_repo = ReminderRepository(db_session)
    svc = ReminderService(session=db_session, repo=rem_repo, item_repo=item_repo)

    item_a = await item_repo.create(user_id=USER_A, type=ItemType.task, content="A task")
    await db_session.commit()
    rem_a = await rem_repo.create(item_id=item_a.id, remind_at=datetime(2030, 1, 1, tzinfo=UTC))
    await db_session.commit()

    # USER_B must not be able to cancel USER_A's reminder.
    cancelled = await svc.cancel_for_user(rem_a.id, USER_B)
    assert cancelled is False

    fresh = await rem_repo.get_by_id_for_user(rem_a.id, USER_A)
    assert fresh is not None
    assert fresh.is_cancelled is False

    # USER_A still can.
    cancelled = await svc.cancel_for_user(rem_a.id, USER_A)
    assert cancelled is True

    fresh = await rem_repo.get_by_id_for_user(rem_a.id, USER_A)
    assert fresh is not None
    assert fresh.is_cancelled is True


async def test_reminder_service_acknowledge_refuses_foreign_owner(
    db_session: AsyncSession,
) -> None:
    item_repo = ItemRepository(db_session)
    rem_repo = ReminderRepository(db_session)
    svc = ReminderService(session=db_session, repo=rem_repo, item_repo=item_repo)

    item_a = await item_repo.create(user_id=USER_A, type=ItemType.task, content="A task")
    await db_session.commit()
    rem_a = await rem_repo.create(item_id=item_a.id, remind_at=datetime(2030, 1, 1, tzinfo=UTC))
    await db_session.commit()

    ack = await svc.acknowledge(reminder_id=rem_a.id, user_id=USER_B)
    assert ack is False

    fresh = await rem_repo.get_by_id_for_user(rem_a.id, USER_A)
    assert fresh is not None
    assert fresh.is_acknowledged is False


async def test_reminder_service_snooze_refuses_foreign_owner(db_session: AsyncSession) -> None:
    item_repo = ItemRepository(db_session)
    rem_repo = ReminderRepository(db_session)
    svc = ReminderService(session=db_session, repo=rem_repo, item_repo=item_repo)

    item_a = await item_repo.create(user_id=USER_A, type=ItemType.task, content="A task")
    await db_session.commit()
    rem_a = await rem_repo.create(item_id=item_a.id, remind_at=datetime(2030, 1, 1, tzinfo=UTC))
    await db_session.commit()

    ok = await svc.snooze(
        reminder_id=rem_a.id,
        user_id=USER_B,
        remind_at=datetime(2030, 1, 5, tzinfo=UTC),
    )
    assert ok is False

    # No new reminder should have been created for USER_B.
    rows = await rem_repo.get_upcoming(USER_B)
    assert rows == []

    fresh = await rem_repo.get_by_id_for_user(rem_a.id, USER_A)
    assert fresh is not None
    assert fresh.is_acknowledged is False


# --- UserSettingsRepository -------------------------------------------------


async def test_user_settings_get_returns_only_own_row(db_session: AsyncSession) -> None:
    repo = UserSettingsRepository(db_session)
    await repo.set_timezone(USER_A, "Europe/Moscow")
    await repo.set_timezone(USER_B, "Asia/Tokyo")
    await db_session.commit()

    settings_a = await repo.get(USER_A)
    settings_b = await repo.get(USER_B)
    assert settings_a is not None and settings_a.timezone == "Europe/Moscow"
    assert settings_b is not None and settings_b.timezone == "Asia/Tokyo"


async def test_user_settings_set_timezone_does_not_touch_other_users(
    db_session: AsyncSession,
) -> None:
    repo = UserSettingsRepository(db_session)
    await repo.set_timezone(USER_A, "Europe/Moscow")
    await repo.set_timezone(USER_B, "Asia/Tokyo")
    await db_session.commit()

    # Updating USER_A must not touch USER_B's row.
    await repo.set_timezone(USER_A, "America/New_York")
    await db_session.commit()

    a = await repo.get(USER_A)
    b = await repo.get(USER_B)
    assert a is not None and a.timezone == "America/New_York"
    assert b is not None and b.timezone == "Asia/Tokyo"


# --- Semantic search isolation ----------------------------------------------
#
# pgvector's ``<=>`` operator is PostgreSQL-only, so the SQL cannot be executed
# against the in-memory SQLite engine used by the integration suite. Instead we
# verify the same isolation invariant by mocking the session, capturing the
# emitted SQL, and asserting that ``items.user_id`` (and the join key for ideas)
# is part of the WHERE clause for the calling user. This proves the query
# physically cannot return another user's rows.


def _capture_execute() -> tuple[MagicMock, MagicMock]:
    """Build a mocked AsyncSession plus an empty result so the query compiles fine."""
    result = MagicMock()
    result.all.return_value = []
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=result)
    return session, result


async def test_item_search_by_embedding_filters_by_user_id_in_sql() -> None:
    from sqlalchemy.dialects import postgresql

    session, _ = _capture_execute()
    repo = ItemRepository(session)

    await repo.search_by_embedding([0.1] * 4, user_id=USER_A, limit=5)

    stmt = session.execute.await_args.args[0]
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    params = dict(stmt.compile(dialect=postgresql.dialect()).params)

    assert "items.user_id" in sql
    assert USER_A in params.values()
    assert USER_B not in params.values()


async def test_idea_search_by_embedding_filters_by_user_id_in_sql() -> None:
    from sqlalchemy.dialects import postgresql

    session, _ = _capture_execute()
    repo = IdeaRepository(session)

    await repo.search_by_embedding([0.1] * 4, user_id=USER_A, limit=5)

    stmt = session.execute.await_args.args[0]
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    params = dict(stmt.compile(dialect=postgresql.dialect()).params)

    assert "items.user_id" in sql
    assert "JOIN ideas" in sql
    assert USER_A in params.values()
    assert USER_B not in params.values()


# --- Sanity guards: stored rows are visibly partitioned ---------------------


async def test_items_with_same_id_field_layout_belong_to_correct_user(
    db_session: AsyncSession,
) -> None:
    """End-to-end sanity check: insert across both users, query each, no overlap."""
    item_repo = ItemRepository(db_session)
    idea_repo = IdeaRepository(db_session)
    rem_repo = ReminderRepository(db_session)

    item_a = await item_repo.create(user_id=USER_A, type=ItemType.idea, content="A idea")
    await idea_repo.save(item_id=item_a.id, tags=["a"])
    rem_a_item = await item_repo.create(user_id=USER_A, type=ItemType.task, content="A task")
    await rem_repo.create(item_id=rem_a_item.id, remind_at=datetime(2030, 1, 1, tzinfo=UTC))

    item_b = await item_repo.create(user_id=USER_B, type=ItemType.idea, content="B idea")
    await idea_repo.save(item_id=item_b.id, tags=["b"])
    rem_b_item = await item_repo.create(user_id=USER_B, type=ItemType.task, content="B task")
    await rem_repo.create(item_id=rem_b_item.id, remind_at=datetime(2030, 1, 2, tzinfo=UTC))

    await db_session.commit()

    # Items
    a_items = await item_repo.get_recent(USER_A, limit=10, offset=0)
    b_items = await item_repo.get_recent(USER_B, limit=10, offset=0)
    assert {it.user_id for it in a_items} == {USER_A}
    assert {it.user_id for it in b_items} == {USER_B}

    # Ideas
    a_ideas = await idea_repo.get_all(USER_A)
    b_ideas = await idea_repo.get_all(USER_B)
    assert {it.user_id for it, _ in a_ideas} == {USER_A}
    assert {it.user_id for it, _ in b_ideas} == {USER_B}

    # Reminders
    a_rems = await rem_repo.get_upcoming(USER_A)
    b_rems = await rem_repo.get_upcoming(USER_B)
    assert len(a_rems) == 1
    assert len(b_rems) == 1
    # Cross-user lookup by ID is denied.
    assert await rem_repo.get_by_id_for_user(a_rems[0].id, USER_B) is None
    assert await rem_repo.get_by_id_for_user(b_rems[0].id, USER_A) is None


async def test_idea_models_have_correct_owner_via_join(db_session: AsyncSession) -> None:
    """A direct sanity check that Idea.item.user_id is always its owner's id."""
    item_repo = ItemRepository(db_session)
    idea_repo = IdeaRepository(db_session)

    item_a = await item_repo.create(user_id=USER_A, type=ItemType.idea, content="A idea")
    idea_a = await idea_repo.save(item_id=item_a.id, tags=[])
    await db_session.commit()

    # Refresh to load the relationship
    await db_session.refresh(idea_a, attribute_names=["item"])
    assert idea_a.item.user_id == USER_A
    # Ensure model types are correct (catches accidental schema changes).
    assert isinstance(idea_a, Idea)
    assert isinstance(idea_a.item, Item)


async def test_reminder_models_have_correct_owner_via_join(db_session: AsyncSession) -> None:
    """Reminder.item.user_id must match its parent Item's user_id."""
    item_repo = ItemRepository(db_session)
    rem_repo = ReminderRepository(db_session)

    item_a = await item_repo.create(user_id=USER_A, type=ItemType.task, content="A task")
    await db_session.commit()
    rem_a = await rem_repo.create(item_id=item_a.id, remind_at=datetime(2030, 1, 1, tzinfo=UTC))
    await db_session.commit()
    await db_session.refresh(rem_a, attribute_names=["item"])

    assert isinstance(rem_a, Reminder)
    assert rem_a.item.user_id == USER_A
    # Spot-check that a foreign user_id lookup returns None on the same record.
    assert await rem_repo.get_by_id_for_user(rem_a.id, USER_B) is None


# Reference the unused import so static checkers don't flag uuid; kept here in
# case future tests need to fabricate forged callback IDs.
_ = uuid.uuid4
