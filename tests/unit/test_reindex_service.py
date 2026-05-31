import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.idea import Idea
from bot.models.item import Item
from bot.repositories.idea_repository import IdeaRepository
from bot.repositories.item_repository import ItemRepository
from bot.services.embedding_service import EmbeddingService
from bot.services.reindex_service import (
    ReindexResult,
    ReindexService,
    ReindexSummary,
)


def make_item(
    *,
    content: str = "item content",
    description: str | None = None,
    scraped_text: str | None = None,
    embedding: list[float] | None = None,
) -> Item:
    """Build a lightweight Item mock with the fields ReindexService reads."""
    item = MagicMock(spec=Item)
    item.id = uuid.uuid4()
    item.content = content
    item.description = description
    item.scraped_text = scraped_text
    item.embedding = embedding
    return item


def make_idea(
    *,
    tags: list[str] | None = None,
    embedding: list[float] | None = None,
    parent_item: Item | None = None,
) -> Idea:
    """Build a lightweight Idea mock with the fields ReindexService reads."""
    idea = MagicMock(spec=Idea)
    idea.id = uuid.uuid4()
    idea.tags = tags or []
    idea.embedding = embedding
    idea.item = parent_item
    return idea


def make_service() -> tuple[
    ReindexService,
    MagicMock,
    MagicMock,
    MagicMock,
    AsyncMock,
]:
    """Build a ReindexService with mocked dependencies; return all collaborators."""
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    embedding = MagicMock(spec=EmbeddingService)
    embedding.generate = AsyncMock()
    item_repo = MagicMock(spec=ItemRepository)
    item_repo.get_by_id_for_user = AsyncMock()
    item_repo.update_embedding = AsyncMock()
    item_repo.list_without_embedding = AsyncMock(return_value=[])
    item_repo.count_without_embedding = AsyncMock(return_value=0)
    idea_repo = MagicMock(spec=IdeaRepository)
    idea_repo.get_by_id_for_user = AsyncMock()
    idea_repo.update_embedding = AsyncMock()
    idea_repo.list_without_embedding = AsyncMock(return_value=[])
    idea_repo.count_without_embedding = AsyncMock(return_value=0)
    svc = ReindexService(
        embedding_service=embedding,
        item_repository=item_repo,
        idea_repository=idea_repo,
        session=session,
    )
    return svc, item_repo, idea_repo, embedding, session.commit


# --- count_unindexed_for_user -----------------------------------------------


async def test_count_unindexed_for_user_sums_item_and_idea_counts() -> None:
    svc, item_repo, idea_repo, _, _ = make_service()
    item_repo.count_without_embedding.return_value = 7
    idea_repo.count_without_embedding.return_value = 3

    total = await svc.count_unindexed_for_user(user_id=42)

    assert total == 10
    item_repo.count_without_embedding.assert_awaited_once_with(42)
    idea_repo.count_without_embedding.assert_awaited_once_with(42)


async def test_count_unindexed_for_user_returns_zero_when_nothing_to_index() -> None:
    svc, item_repo, idea_repo, _, _ = make_service()
    item_repo.count_without_embedding.return_value = 0
    idea_repo.count_without_embedding.return_value = 0

    total = await svc.count_unindexed_for_user(user_id=1)

    assert total == 0


# --- reindex_item -----------------------------------------------------------


async def test_reindex_item_success_persists_vector_and_commits() -> None:
    svc, item_repo, _, embedding, commit = make_service()
    item = make_item(content="hello")
    item_repo.get_by_id_for_user.return_value = item
    embedding.generate.return_value = [0.1] * 4

    result = await svc.reindex_item(item.id, user_id=42)

    assert result is ReindexResult.SUCCESS
    embedding.generate.assert_awaited_once_with("hello")
    item_repo.update_embedding.assert_awaited_once_with(item.id, [0.1] * 4)
    commit.assert_awaited_once()


async def test_reindex_item_returns_not_found_for_foreign_or_missing_id() -> None:
    svc, item_repo, _, embedding, commit = make_service()
    item_repo.get_by_id_for_user.return_value = None

    result = await svc.reindex_item(uuid.uuid4(), user_id=42)

    assert result is ReindexResult.NOT_FOUND
    embedding.generate.assert_not_awaited()
    commit.assert_not_awaited()


async def test_reindex_item_returns_already_indexed_when_embedding_present() -> None:
    svc, item_repo, _, embedding, commit = make_service()
    item = make_item(embedding=[0.2] * 4)
    item_repo.get_by_id_for_user.return_value = item

    result = await svc.reindex_item(item.id, user_id=42)

    assert result is ReindexResult.ALREADY_INDEXED
    embedding.generate.assert_not_awaited()
    commit.assert_not_awaited()


async def test_reindex_item_returns_service_unavailable_when_voyage_returns_none() -> None:
    svc, item_repo, _, embedding, commit = make_service()
    item = make_item()
    item_repo.get_by_id_for_user.return_value = item
    embedding.generate.return_value = None

    result = await svc.reindex_item(item.id, user_id=42)

    assert result is ReindexResult.SERVICE_UNAVAILABLE
    item_repo.update_embedding.assert_not_awaited()
    commit.assert_not_awaited()


# --- reindex_idea -----------------------------------------------------------


async def test_reindex_idea_success_persists_vector_and_commits() -> None:
    svc, _, idea_repo, embedding, commit = make_service()
    parent = make_item(content="parent content")
    idea = make_idea(tags=["t1"], parent_item=parent)
    idea_repo.get_by_id_for_user.return_value = idea
    embedding.generate.return_value = [0.3] * 4

    result = await svc.reindex_idea(idea.id, user_id=42)

    assert result is ReindexResult.SUCCESS
    # Text combines the parent content with a Russian-tagged "Теги:" line.
    expected_text = "parent content\n\nТеги: t1"
    embedding.generate.assert_awaited_once_with(expected_text)
    idea_repo.update_embedding.assert_awaited_once_with(idea.id, [0.3] * 4)
    commit.assert_awaited_once()


async def test_reindex_idea_returns_not_found_for_foreign_or_missing_id() -> None:
    svc, _, idea_repo, embedding, commit = make_service()
    idea_repo.get_by_id_for_user.return_value = None

    result = await svc.reindex_idea(uuid.uuid4(), user_id=42)

    assert result is ReindexResult.NOT_FOUND
    embedding.generate.assert_not_awaited()
    commit.assert_not_awaited()


async def test_reindex_idea_returns_already_indexed_when_embedding_present() -> None:
    svc, _, idea_repo, embedding, commit = make_service()
    idea = make_idea(embedding=[0.4] * 4)
    idea_repo.get_by_id_for_user.return_value = idea

    result = await svc.reindex_idea(idea.id, user_id=42)

    assert result is ReindexResult.ALREADY_INDEXED
    embedding.generate.assert_not_awaited()
    commit.assert_not_awaited()


async def test_reindex_idea_returns_service_unavailable_when_voyage_returns_none() -> None:
    svc, _, idea_repo, embedding, commit = make_service()
    parent = make_item(content="parent")
    idea = make_idea(parent_item=parent)
    idea_repo.get_by_id_for_user.return_value = idea
    embedding.generate.return_value = None

    result = await svc.reindex_idea(idea.id, user_id=42)

    assert result is ReindexResult.SERVICE_UNAVAILABLE
    idea_repo.update_embedding.assert_not_awaited()
    commit.assert_not_awaited()


# --- reindex_all_for_user ---------------------------------------------------


async def test_reindex_all_for_user_empty_backlog_returns_zero_summary() -> None:
    svc, item_repo, idea_repo, embedding, commit = make_service()
    item_repo.list_without_embedding.return_value = []
    idea_repo.list_without_embedding.return_value = []

    summary = await svc.reindex_all_for_user(user_id=42)

    assert summary == ReindexSummary(succeeded=0, failed=0, total_found=0, truncated=False)
    embedding.generate.assert_not_awaited()
    commit.assert_not_awaited()


async def test_reindex_all_aborts_when_first_call_returns_none() -> None:
    svc, item_repo, idea_repo, embedding, commit = make_service()
    a = make_item(content="a")
    b = make_item(content="b")
    item_repo.list_without_embedding.return_value = [a, b]
    parent = make_item(content="parent")
    idea = make_idea(parent_item=parent)
    idea_repo.list_without_embedding.return_value = [(parent, idea)]
    embedding.generate.return_value = None

    summary = await svc.reindex_all_for_user(user_id=42)

    # The first Voyage call short-circuits; nothing should have been written.
    assert summary == ReindexSummary(succeeded=0, failed=3, total_found=3, truncated=False)
    assert embedding.generate.await_count == 1
    item_repo.update_embedding.assert_not_awaited()
    idea_repo.update_embedding.assert_not_awaited()
    commit.assert_not_awaited()


async def test_reindex_all_aborts_when_first_idea_call_returns_none_with_no_items() -> None:
    """When items are absent and the first idea call fails, the whole pass is aborted."""
    svc, item_repo, idea_repo, embedding, commit = make_service()
    item_repo.list_without_embedding.return_value = []
    parent_one = make_item(content="p1")
    parent_two = make_item(content="p2")
    idea_one = make_idea(tags=["a"], parent_item=parent_one)
    idea_two = make_idea(tags=["b"], parent_item=parent_two)
    idea_repo.list_without_embedding.return_value = [
        (parent_one, idea_one),
        (parent_two, idea_two),
    ]
    embedding.generate.return_value = None

    summary = await svc.reindex_all_for_user(user_id=42)

    assert summary == ReindexSummary(succeeded=0, failed=2, total_found=2, truncated=False)
    assert embedding.generate.await_count == 1
    idea_repo.update_embedding.assert_not_awaited()
    commit.assert_not_awaited()


async def test_reindex_all_partial_failure_counts_only_failed_record() -> None:
    svc, item_repo, idea_repo, embedding, commit = make_service()
    good_item = make_item(content="ok-item")
    bad_item = make_item(content="bad-item")
    parent = make_item(content="parent")
    idea = make_idea(tags=["x"], parent_item=parent)
    item_repo.list_without_embedding.return_value = [good_item, bad_item]
    idea_repo.list_without_embedding.return_value = [(parent, idea)]

    # First call succeeds, second returns None (treated as a per-record failure),
    # third (idea) succeeds again.
    embedding.generate.side_effect = [
        [0.1] * 4,
        None,
        [0.2] * 4,
    ]

    summary = await svc.reindex_all_for_user(user_id=42)

    assert summary == ReindexSummary(succeeded=2, failed=1, total_found=3, truncated=False)
    # Only the two successful generations wrote and committed.
    item_repo.update_embedding.assert_awaited_once_with(good_item.id, [0.1] * 4)
    idea_repo.update_embedding.assert_awaited_once_with(idea.id, [0.2] * 4)
    assert commit.await_count == 2


async def test_reindex_all_ideas_only_partial_failure() -> None:
    """When only ideas are unindexed, mid-pass None counts as a per-record failure."""
    svc, item_repo, idea_repo, embedding, commit = make_service()
    item_repo.list_without_embedding.return_value = []
    parent_a = make_item(content="pa")
    parent_b = make_item(content="pb")
    idea_a = make_idea(tags=["a"], parent_item=parent_a)
    idea_b = make_idea(tags=["b"], parent_item=parent_b)
    idea_repo.list_without_embedding.return_value = [
        (parent_a, idea_a),
        (parent_b, idea_b),
    ]
    embedding.generate.side_effect = [[0.1] * 4, None]

    summary = await svc.reindex_all_for_user(user_id=42)

    assert summary == ReindexSummary(succeeded=1, failed=1, total_found=2, truncated=False)
    idea_repo.update_embedding.assert_awaited_once_with(idea_a.id, [0.1] * 4)
    commit.assert_awaited_once()


async def test_reindex_all_truncates_when_backlog_exceeds_max_items() -> None:
    svc, item_repo, idea_repo, embedding, commit = make_service()
    # max_items=2, so we load 2 items (filling the budget) and 0 ideas, but the
    # backlog count reports 5 total → truncated must be True.
    a = make_item(content="a")
    b = make_item(content="b")
    item_repo.list_without_embedding.return_value = [a, b]
    item_repo.count_without_embedding.return_value = 5
    idea_repo.count_without_embedding.return_value = 0
    embedding.generate.return_value = [0.9] * 4

    summary = await svc.reindex_all_for_user(user_id=42, max_items=2)

    assert summary == ReindexSummary(succeeded=2, failed=0, total_found=2, truncated=True)
    # When the items budget is exhausted, ideas must not be loaded.
    idea_repo.list_without_embedding.assert_not_awaited()
    assert commit.await_count == 2


async def test_reindex_all_does_not_call_count_when_window_underfills_budget() -> None:
    """When the loaded window leaves slack, no count query is needed to confirm not-truncated."""
    svc, item_repo, idea_repo, embedding, _ = make_service()
    a = make_item(content="a")
    item_repo.list_without_embedding.return_value = [a]
    idea_repo.list_without_embedding.return_value = []
    embedding.generate.return_value = [0.5] * 4

    summary = await svc.reindex_all_for_user(user_id=42, max_items=10)

    assert summary.truncated is False
    item_repo.count_without_embedding.assert_not_awaited()
    idea_repo.count_without_embedding.assert_not_awaited()


async def test_reindex_all_isolates_ideas_via_repository_user_filter() -> None:
    """The bulk path must call list_without_embedding with user_id — no global scan."""
    svc, item_repo, idea_repo, _, _ = make_service()
    item_repo.list_without_embedding.return_value = []
    idea_repo.list_without_embedding.return_value = []

    await svc.reindex_all_for_user(user_id=777)

    item_repo.list_without_embedding.assert_awaited_once_with(777, limit=200)
    idea_repo.list_without_embedding.assert_awaited_once_with(777, limit=200)


# --- helper text builders ---------------------------------------------------


def test_build_item_text_joins_all_non_empty_fields() -> None:
    item = make_item(
        content="The body",
        description="A short note",
        scraped_text="Full scraped text",
    )
    text = ReindexService._build_item_text(item)
    assert text == "The body\n\nA short note\n\nFull scraped text"


def test_build_item_text_skips_empty_fields() -> None:
    item = make_item(content="just content")
    text = ReindexService._build_item_text(item)
    assert text == "just content"


def test_build_idea_text_combines_parent_content_and_tags() -> None:
    parent = make_item(content="Idea body")
    idea = make_idea(tags=["one", "two"], parent_item=parent)
    text = ReindexService._build_idea_text(idea)
    assert text == "Idea body\n\nТеги: one, two"


def test_build_idea_text_without_parent_or_tags_returns_empty() -> None:
    idea = make_idea(tags=[], parent_item=None)
    text = ReindexService._build_idea_text(idea)
    assert text == ""


# --- enum / dataclass smoke -------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        ReindexResult.SUCCESS,
        ReindexResult.ALREADY_INDEXED,
        ReindexResult.NOT_FOUND,
        ReindexResult.SERVICE_UNAVAILABLE,
    ],
)
def test_reindex_result_values_are_distinct(value: ReindexResult) -> None:
    assert isinstance(value.value, str)
    assert value.value
