import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.exceptions import SemanticSearchUnavailableError
from bot.models.idea import Idea
from bot.models.item import Item, ItemType
from bot.repositories.idea_repository import IdeaRepository
from bot.repositories.item_repository import ItemRepository
from bot.services.embedding_service import EmbeddingService
from bot.services.semantic_search_service import SearchResult, SemanticSearchService


def make_item(
    *,
    content: str = "Some content",
    description: str | None = None,
    title: str | None = None,
    item_type: ItemType | None = None,
    scraped_text: str | None = None,
    created_at: datetime | None = None,
) -> Item:
    item = MagicMock(spec=Item)
    item.id = uuid.uuid4()
    item.user_id = 1
    item.content = content
    item.description = description
    item.title = title
    item.scraped_text = scraped_text
    item.type = item_type or ItemType.note
    item.created_at = created_at or datetime.now(UTC)
    return item


def make_idea(
    *,
    tags: list[str] | None = None,
) -> Idea:
    idea = MagicMock(spec=Idea)
    idea.id = uuid.uuid4()
    idea.tags = tags if tags is not None else []
    return idea


def make_service(
    *,
    query_vector: list[float] | None = None,
    item_hits: list[tuple[Item, float]] | None = None,
    idea_hits: list[tuple[Item, Idea, float]] | None = None,
) -> tuple[SemanticSearchService, EmbeddingService, ItemRepository, IdeaRepository]:
    embedding = MagicMock(spec=EmbeddingService)
    embedding.generate = AsyncMock(return_value=query_vector)

    item_repo = MagicMock(spec=ItemRepository)
    item_repo.search_by_embedding = AsyncMock(return_value=item_hits or [])

    idea_repo = MagicMock(spec=IdeaRepository)
    idea_repo.search_by_embedding = AsyncMock(return_value=idea_hits or [])

    svc = SemanticSearchService(
        embedding_service=embedding,
        item_repo=item_repo,
        idea_repo=idea_repo,
    )
    return svc, embedding, item_repo, idea_repo


# ─── search: happy path ──────────────────────────────────────────────────────


async def test_search_generates_query_embedding() -> None:
    vec = [0.1, 0.2, 0.3, 0.4]
    svc, embedding, _, _ = make_service(query_vector=vec)

    await svc.search(user_id=1, query="python tips")

    embedding.generate.assert_awaited_once_with("python tips")


async def test_search_returns_items_and_ideas_sorted_by_score() -> None:
    item_a = make_item(content="low-score item")
    item_b = make_item(content="high-score item")
    idea_item = make_item(content="middle-score idea")
    idea = make_idea(tags=["creative"])
    svc, _, item_repo, idea_repo = make_service(
        query_vector=[0.1, 0.2, 0.3, 0.4],
        item_hits=[(item_a, 0.2), (item_b, 0.9)],
        idea_hits=[(idea_item, idea, 0.5)],
    )

    results = await svc.search(user_id=1, query="q")

    assert [r.score for r in results] == [0.9, 0.5, 0.2]
    assert results[0].type == "item"
    assert results[0].id == item_b.id
    assert results[1].type == "idea"
    assert results[1].id == idea.id
    assert results[2].type == "item"
    assert results[2].id == item_a.id

    # Both repositories received the generated embedding and the user_id.
    item_repo.search_by_embedding.assert_awaited_once()
    assert item_repo.search_by_embedding.await_args.args[0] == [0.1, 0.2, 0.3, 0.4]
    assert item_repo.search_by_embedding.await_args.args[1] == 1
    idea_repo.search_by_embedding.assert_awaited_once()
    assert idea_repo.search_by_embedding.await_args.args[0] == [0.1, 0.2, 0.3, 0.4]


async def test_search_builds_search_result_fields() -> None:
    created = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    item = make_item(
        content="Watch https://example.com\nsecond line",
        description="Example description",
        created_at=created,
    )
    svc, _, _, _ = make_service(query_vector=[0.1] * 4, item_hits=[(item, 0.42)])

    results = await svc.search(user_id=1, query="q")

    assert len(results) == 1
    r = results[0]
    assert isinstance(r, SearchResult)
    assert r.id == item.id
    assert r.type == "item"
    assert r.title == "Watch https://example.com"
    assert r.preview_text == "Example description"
    assert r.score == 0.42
    assert r.created_at == created


async def test_search_idea_preview_includes_tags() -> None:
    parent = make_item(content="Build a rocket")
    idea = make_idea(tags=["space", "rocket"])
    svc, _, _, _ = make_service(query_vector=[0.1] * 4, idea_hits=[(parent, idea, 0.7)])

    results = await svc.search(user_id=1, query="q")

    assert len(results) == 1
    assert results[0].type == "idea"
    assert results[0].id == idea.id
    assert "space" in results[0].preview_text
    assert "rocket" in results[0].preview_text
    assert "Build a rocket" in results[0].preview_text


async def test_search_idea_preview_without_tags_falls_back_to_content() -> None:
    parent = make_item(content="Plain content")
    idea = make_idea(tags=[])
    svc, _, _, _ = make_service(query_vector=[0.1] * 4, idea_hits=[(parent, idea, 0.7)])

    results = await svc.search(user_id=1, query="q")

    assert results[0].preview_text == "Plain content"


async def test_search_item_preview_falls_back_to_content_when_no_description() -> None:
    item = make_item(content="just the content", description=None)
    svc, _, _, _ = make_service(query_vector=[0.1] * 4, item_hits=[(item, 0.1)])

    results = await svc.search(user_id=1, query="q")

    assert results[0].preview_text == "just the content"


async def test_search_title_truncates_very_long_first_line() -> None:
    long_line = "a" * 500
    item = make_item(content=long_line)
    svc, _, _, _ = make_service(query_vector=[0.1] * 4, item_hits=[(item, 0.1)])

    results = await svc.search(user_id=1, query="q")

    assert len(results[0].title) <= 200


async def test_search_title_skips_blank_first_lines() -> None:
    item = make_item(content="   \n\nreal first line\nsecond line")
    svc, _, _, _ = make_service(query_vector=[0.1] * 4, item_hits=[(item, 0.1)])

    results = await svc.search(user_id=1, query="q")

    assert results[0].title == "real first line"


async def test_search_title_falls_back_when_content_is_blank() -> None:
    item = make_item(content="   \n\n\n")
    svc, _, _, _ = make_service(query_vector=[0.1] * 4, item_hits=[(item, 0.1)])

    results = await svc.search(user_id=1, query="q")

    assert results[0].title == ""


async def test_search_idea_preview_with_tags_but_blank_content() -> None:
    parent = make_item(content="   ")
    idea = make_idea(tags=["alpha", "beta"])
    svc, _, _, _ = make_service(query_vector=[0.1] * 4, idea_hits=[(parent, idea, 0.3)])

    results = await svc.search(user_id=1, query="q")

    assert results[0].preview_text == "alpha, beta"


# ─── search: error + empty ───────────────────────────────────────────────────


async def test_search_raises_when_embedding_unavailable() -> None:
    svc, _, item_repo, idea_repo = make_service(query_vector=None)

    with pytest.raises(SemanticSearchUnavailableError):
        await svc.search(user_id=1, query="q")

    item_repo.search_by_embedding.assert_not_awaited()
    idea_repo.search_by_embedding.assert_not_awaited()


async def test_search_returns_empty_when_no_hits() -> None:
    svc, _, _, _ = make_service(query_vector=[0.1] * 4, item_hits=[], idea_hits=[])

    assert await svc.search(user_id=1, query="q") == []


# ─── search: pagination ──────────────────────────────────────────────────────


async def test_search_applies_limit() -> None:
    hits = [(make_item(content=f"item {i}"), 1.0 - i * 0.01) for i in range(5)]
    svc, _, _, _ = make_service(query_vector=[0.1] * 4, item_hits=hits)

    results = await svc.search(user_id=1, query="q", limit=2)

    assert len(results) == 2
    assert [r.score for r in results] == [1.0, 0.99]


async def test_search_applies_offset_and_limit() -> None:
    hits = [(make_item(content=f"item {i}"), 1.0 - i * 0.01) for i in range(5)]
    svc, _, _, _ = make_service(query_vector=[0.1] * 4, item_hits=hits)

    results = await svc.search(user_id=1, query="q", limit=2, offset=2)

    # After sorting desc the scores are [1.0, 0.99, 0.98, 0.97, 0.96].
    # Offset 2, limit 2 → [0.98, 0.97].
    assert [r.score for r in results] == [0.98, 0.97]


async def test_search_fetches_enough_rows_for_offset_window() -> None:
    svc, _, item_repo, idea_repo = make_service(query_vector=[0.1] * 4)

    await svc.search(user_id=1, query="q", limit=10, offset=20)

    # Each repo must be asked for at least ``limit + offset`` rows so the merged,
    # sorted window can satisfy the requested page.
    assert item_repo.search_by_embedding.await_args.kwargs["limit"] == 30
    assert idea_repo.search_by_embedding.await_args.kwargs["limit"] == 30


async def test_search_offset_beyond_results_returns_empty_list() -> None:
    item = make_item(content="only hit")
    svc, _, _, _ = make_service(query_vector=[0.1] * 4, item_hits=[(item, 0.9)])

    results = await svc.search(user_id=1, query="q", limit=10, offset=5)

    assert results == []


async def test_search_link_uses_stored_title_for_search_result() -> None:
    """A link Item with ``title`` set surfaces it as the SearchResult title."""
    item = make_item(
        content="https://example.com/article",
        title="My Headline",
        scraped_text="The article body…",
        item_type=ItemType.link,
    )
    svc, _, _, _ = make_service(query_vector=[0.1] * 4, item_hits=[(item, 0.6)])

    results = await svc.search(user_id=1, query="q")

    assert results[0].title == "My Headline"
    assert results[0].url == "https://example.com/article"
    assert results[0].item_type == "link"
    # Preview comes from scraped_text for links so users see the article body.
    assert results[0].preview_text.startswith("The article body")


async def test_search_link_without_title_falls_back_to_url_as_title() -> None:
    """A link without a stored title displays the URL as the SearchResult title."""
    item = make_item(
        content="https://example.com/raw",
        title=None,
        scraped_text=None,
        item_type=ItemType.link,
    )
    svc, _, _, _ = make_service(query_vector=[0.1] * 4, item_hits=[(item, 0.4)])

    results = await svc.search(user_id=1, query="q")

    assert results[0].title == "https://example.com/raw"
    # Empty preview when there is no scraped_text — the renderer hides the
    # "Текст:" line in this case.
    assert results[0].preview_text == ""


async def test_search_link_preview_uses_scraped_text_not_description() -> None:
    """For links, the preview line is built from ``scraped_text`` only."""
    item = make_item(
        content="https://example.com/x",
        title="Hdr",
        description="Should be ignored for links",
        scraped_text="Real body of the article goes here.",
        item_type=ItemType.link,
    )
    svc, _, _, _ = make_service(query_vector=[0.1] * 4, item_hits=[(item, 0.5)])

    results = await svc.search(user_id=1, query="q")

    assert "Real body of the article" in results[0].preview_text
    assert "ignored" not in results[0].preview_text


async def test_search_media_uses_description_as_title() -> None:
    """A media Item exposes its Vision description as the SearchResult title."""
    drive_link = "https://drive.google.com/file/d/abc"
    item = make_item(
        content=drive_link,
        description="Receipt from supermarket",
        item_type=ItemType.media,
    )
    svc, _, _, _ = make_service(query_vector=[0.1] * 4, item_hits=[(item, 0.7)])

    results = await svc.search(user_id=1, query="q")

    assert results[0].title == "Receipt from supermarket"
    assert results[0].url == drive_link
    assert results[0].item_type == "media"


async def test_search_carries_item_type_for_non_link_items() -> None:
    """``item_type`` round-trips so the formatter can pick the right emoji/label."""
    note_item = make_item(content="just a note", item_type=ItemType.note)
    task_item = make_item(content="buy milk", item_type=ItemType.task)
    svc, _, _, _ = make_service(
        query_vector=[0.1] * 4, item_hits=[(note_item, 0.8), (task_item, 0.7)]
    )

    results = await svc.search(user_id=1, query="q")

    by_id = {r.id: r for r in results}
    assert by_id[note_item.id].item_type == "note"
    assert by_id[note_item.id].url is None
    assert by_id[task_item.id].item_type == "task"
    assert by_id[task_item.id].url is None


async def test_search_idea_does_not_carry_url() -> None:
    """Idea hits never carry a URL — they're rendered through the [идея] label only."""
    parent = make_item(content="some idea text")
    idea = make_idea(tags=["tag"])
    svc, _, _, _ = make_service(query_vector=[0.1] * 4, idea_hits=[(parent, idea, 0.5)])

    results = await svc.search(user_id=1, query="q")

    assert results[0].type == "idea"
    assert results[0].item_type == "idea"
    assert results[0].url is None


async def test_search_passes_user_id_through() -> None:
    svc, _, item_repo, idea_repo = make_service(query_vector=[0.1] * 4)

    await svc.search(user_id=42, query="q")

    assert item_repo.search_by_embedding.await_args.args[1] == 42
    assert idea_repo.search_by_embedding.await_args.args[1] == 42
