"""Unit tests for web/services/item_service.py."""

import uuid
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from bot.repositories.item_repository import ItemRepository
from web.services.item_service import ItemService


def make_service() -> tuple[ItemService, MagicMock, MagicMock]:
    """Return (service, repo_mock, session_mock) with async stubs wired up."""
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    repo = MagicMock(spec=ItemRepository)
    svc = ItemService(session=session, item_repo=repo)
    return svc, repo, session


# ---------------------------------------------------------------------------
# delete_item
# ---------------------------------------------------------------------------


async def test_delete_item_found_commits_and_returns_true() -> None:
    """When the item exists and belongs to the user, it is deleted and commit is called."""
    svc, repo, session = make_service()
    repo.delete_for_user = AsyncMock(return_value=True)
    item_id = uuid.uuid4()

    result = await svc.delete_item(item_id, user_id=1)

    repo.delete_for_user.assert_awaited_once_with(item_id, 1)
    session.commit.assert_awaited_once()
    assert result is True


async def test_delete_item_not_found_skips_commit_and_returns_false() -> None:
    """When the item does not exist or belongs to another user, commit is not called."""
    svc, repo, session = make_service()
    repo.delete_for_user = AsyncMock(return_value=False)
    item_id = uuid.uuid4()

    result = await svc.delete_item(item_id, user_id=1)

    repo.delete_for_user.assert_awaited_once_with(item_id, 1)
    session.commit.assert_not_called()
    assert result is False


async def test_delete_item_passes_correct_user_id() -> None:
    """The user_id argument is forwarded to the repository unchanged."""
    svc, repo, session = make_service()
    repo.delete_for_user = AsyncMock(return_value=True)
    item_id = uuid.uuid4()

    await svc.delete_item(item_id, user_id=42)

    repo.delete_for_user.assert_awaited_once_with(item_id, 42)


# ---------------------------------------------------------------------------
# bulk_delete_items
# ---------------------------------------------------------------------------


async def test_bulk_delete_empty_list_returns_zero_without_repo_call() -> None:
    """An empty id list short-circuits before calling the repository."""
    svc, repo, session = make_service()
    repo.bulk_delete_for_user = AsyncMock(return_value=0)

    result = await svc.bulk_delete_items([], user_id=1)

    repo.bulk_delete_for_user.assert_not_called()
    session.commit.assert_not_called()
    assert result == 0


async def test_bulk_delete_some_deleted_commits_and_returns_count() -> None:
    """When at least one item is deleted, commit is called and the count is returned."""
    svc, repo, session = make_service()
    ids = [uuid.uuid4(), uuid.uuid4()]
    repo.bulk_delete_for_user = AsyncMock(return_value=2)

    result = await svc.bulk_delete_items(ids, user_id=1)

    repo.bulk_delete_for_user.assert_awaited_once_with(ids, 1)
    session.commit.assert_awaited_once()
    assert result == 2


async def test_bulk_delete_none_deleted_skips_commit() -> None:
    """When no items match (count == 0), commit is not called."""
    svc, repo, session = make_service()
    ids = [uuid.uuid4()]
    repo.bulk_delete_for_user = AsyncMock(return_value=0)

    result = await svc.bulk_delete_items(ids, user_id=1)

    repo.bulk_delete_for_user.assert_awaited_once_with(ids, 1)
    session.commit.assert_not_called()
    assert result == 0


async def test_bulk_delete_passes_correct_user_id() -> None:
    """The user_id argument is forwarded to the repository unchanged."""
    svc, repo, session = make_service()
    ids = [uuid.uuid4()]
    repo.bulk_delete_for_user = AsyncMock(return_value=1)

    await svc.bulk_delete_items(ids, user_id=99)

    repo.bulk_delete_for_user.assert_awaited_once_with(ids, 99)


async def test_bulk_delete_partial_match_returns_actual_count() -> None:
    """When only some of the given ids are owned by the user, the actual count is returned."""
    svc, repo, session = make_service()
    ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    repo.bulk_delete_for_user = AsyncMock(return_value=1)

    result = await svc.bulk_delete_items(ids, user_id=7)

    assert result == 1
    session.commit.assert_awaited_once()
