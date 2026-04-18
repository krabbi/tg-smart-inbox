import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from bot.exceptions import ScrapingError
from bot.models.item import Item, ItemType
from bot.repositories.item_repository import ItemRepository
from bot.services.claude_client import ClaudeClient
from bot.services.embedding_service import EmbeddingService
from bot.services.link_service import _SUMMARIZE_PROMPT, LinkService, LinkSummary, SavedLink
from bot.services.scraper import Scraper

_PLAIN_RESPONSE = (
    "Как печь хлеб\n\nВыпечка хлеба — это просто. Используй сильную муку."
    "\n• Совет один\n• Совет два"
)


def make_link_service(
    *,
    scraper_text: str = "page text",
    claude_response: str = _PLAIN_RESPONSE,
    session: AsyncSession | None = None,
    embedding: list[float] | None = None,
    cached_item: Item | None = None,
) -> tuple[LinkService, ItemRepository]:
    mock_session = session or MagicMock(spec=AsyncSession)
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    mock_item = MagicMock(spec=Item)
    mock_item.id = uuid.uuid4()
    mock_item.type = ItemType.link
    mock_item.content = "https://example.com"
    mock_item.scraped_text = None

    mock_repo = MagicMock(spec=ItemRepository)
    mock_repo.create = AsyncMock(return_value=mock_item)
    mock_repo.update_embedding = AsyncMock()
    mock_repo.update_scraped_text = AsyncMock()
    mock_repo.get_by_id = AsyncMock(return_value=cached_item)

    mock_scraper = MagicMock(spec=Scraper)
    mock_scraper.fetch_text = AsyncMock(return_value=scraper_text)

    mock_claude = MagicMock(spec=ClaudeClient)
    mock_claude.complete = AsyncMock(return_value=claude_response)

    mock_embedding = MagicMock(spec=EmbeddingService)
    mock_embedding.generate_for_item = AsyncMock(return_value=embedding)

    svc = LinkService(
        session=mock_session,
        item_repo=mock_repo,
        scraper=mock_scraper,
        claude=mock_claude,
        embedding_service=mock_embedding,
    )
    return svc, mock_repo


async def test_save_creates_item_with_link_type() -> None:
    svc, repo = make_link_service()
    await svc.save("https://example.com", user_id=123)
    repo.create.assert_awaited_once_with(  # type: ignore[attr-defined]
        user_id=123, type=ItemType.link, content="https://example.com"
    )


async def test_save_commits_session() -> None:
    mock_session = MagicMock(spec=AsyncSession)
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()
    svc, _ = make_link_service(session=mock_session)
    await svc.save("https://example.com", user_id=1)
    # First commit persists the Item; optional second commit persists the embedding.
    assert mock_session.commit.await_count >= 1


async def test_save_returns_saved_link() -> None:
    svc, _ = make_link_service()
    saved = await svc.save("https://example.com", user_id=1)
    assert isinstance(saved, SavedLink)
    assert saved.item is not None
    assert saved.item.type == ItemType.link


async def test_save_without_embedding_service_returns_not_indexed() -> None:
    """When no EmbeddingService is wired, the record is still saved but not indexed."""
    mock_session = MagicMock(spec=AsyncSession)
    mock_session.commit = AsyncMock()
    mock_repo = MagicMock(spec=ItemRepository)
    mock_item = MagicMock(spec=Item)
    mock_item.id = uuid.uuid4()
    mock_item.type = ItemType.link
    mock_item.scraped_text = None
    mock_repo.create = AsyncMock(return_value=mock_item)

    mock_scraper = MagicMock(spec=Scraper)
    mock_scraper.fetch_text = AsyncMock(return_value="page body")

    svc = LinkService(
        session=mock_session,
        item_repo=mock_repo,
        scraper=mock_scraper,
        claude=MagicMock(spec=ClaudeClient),
        embedding_service=None,
    )
    saved = await svc.save("https://example.com", user_id=1)
    assert saved.indexed is False


async def test_save_indexes_item_when_embedding_succeeds() -> None:
    svc, repo = make_link_service(embedding=[0.1] * 1536)
    saved = await svc.save("https://example.com", user_id=1)
    assert saved.indexed is True
    repo.update_embedding.assert_awaited_once()  # type: ignore[attr-defined]


async def test_save_marks_not_indexed_when_embedding_returns_none() -> None:
    svc, repo = make_link_service(embedding=None)
    saved = await svc.save("https://example.com", user_id=1)
    assert saved.indexed is False
    repo.update_embedding.assert_not_awaited()  # type: ignore[attr-defined]


async def test_save_handles_embedding_service_exception() -> None:
    """Embedding crashes must never break the save — item is returned, indexed=False."""
    svc, _ = make_link_service()
    svc._embedding.generate_for_item = AsyncMock(side_effect=Exception("API down"))  # type: ignore[attr-defined, union-attr]
    saved = await svc.save("https://example.com", user_id=1)
    assert saved.indexed is False
    assert saved.item is not None


async def test_save_rolls_back_when_update_embedding_fails() -> None:
    """If persisting the vector blows up, the service rolls back and reports not indexed."""
    mock_session = MagicMock(spec=AsyncSession)
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()
    svc, repo = make_link_service(session=mock_session, embedding=[0.1] * 1536)
    repo.update_embedding = AsyncMock(side_effect=Exception("DB blew up"))  # type: ignore[attr-defined]

    saved = await svc.save("https://example.com", user_id=1)

    assert saved.indexed is False
    mock_session.rollback.assert_awaited_once()


async def test_summarize_calls_scraper_and_claude() -> None:
    svc, _ = make_link_service()
    result = await svc.summarize("https://example.com")
    assert isinstance(result, LinkSummary)
    assert result.title == "Как печь хлеб"
    assert "просто" in result.body
    assert result.url == "https://example.com"


async def test_summarize_raises_scraping_error() -> None:
    svc, _ = make_link_service()
    svc._scraper.fetch_text = AsyncMock(side_effect=ScrapingError("timeout"))  # type: ignore[attr-defined]
    with pytest.raises(ScrapingError):
        await svc.summarize("https://example.com")


# ── language requirement ─────────────────────────────────────────────────────


async def test_summarize_prompt_template_is_language_neutral() -> None:
    """Prompt template must use a placeholder, never hardcode a specific language."""
    assert "{language}" in _SUMMARIZE_PROMPT
    # The previous hardcoded "Russian" directive is gone — the language is
    # interpolated per-request from the caller's ``lang`` argument.
    assert "Russian" not in _SUMMARIZE_PROMPT
    # Must still cover the case when the source page is in another language.
    assert "regardless of the original language" in _SUMMARIZE_PROMPT


async def test_summarize_sends_russian_instruction_when_lang_ru() -> None:
    """When lang='ru' the prompt sent to Claude must instruct a Russian response."""
    english_page = (
        "Bread baking is a wonderful hobby. You need flour, water, salt and yeast. "
        "Mix, knead, proof, bake. Enjoy fresh bread at home."
    )
    svc, _ = make_link_service(
        scraper_text=english_page,
        claude_response="Как печь хлеб\n\nСтатья о домашней выпечке хлеба.",
    )
    result = await svc.summarize("https://example.com/bread", lang="ru")

    svc._claude.complete.assert_awaited_once()  # type: ignore[attr-defined]
    sent_prompt = svc._claude.complete.await_args.args[0]  # type: ignore[attr-defined]
    assert "Russian" in sent_prompt
    assert "regardless of the original language" in sent_prompt
    assert english_page in sent_prompt

    # Title and body come back in Russian (as Claude was instructed to translate).
    assert result.title == "Как печь хлеб"
    assert "выпечке" in result.body


async def test_summarize_sends_english_instruction_when_lang_en() -> None:
    """When lang='en' the prompt sent to Claude must instruct an English response."""
    russian_page = "Выпечка хлеба — это чудесное хобби."
    svc, _ = make_link_service(
        scraper_text=russian_page,
        claude_response="Bread baking\n\nA page about baking bread at home.",
    )
    await svc.summarize("https://example.com/bread", lang="en")

    sent_prompt = svc._claude.complete.await_args.args[0]  # type: ignore[attr-defined]
    assert "English" in sent_prompt
    # With lang='en' there must be no Russian directive in the prompt.
    assert "Russian" not in sent_prompt


async def test_summarize_default_lang_is_english() -> None:
    """Omitting lang falls back to the default (English) — not Russian."""
    svc, _ = make_link_service()
    await svc.summarize("https://example.com")

    sent_prompt = svc._claude.complete.await_args.args[0]  # type: ignore[attr-defined]
    assert "English" in sent_prompt
    assert "Russian" not in sent_prompt


async def test_summarize_returns_russian_for_non_english_source() -> None:
    """Summary for a page in any foreign language is returned in the requested language."""
    french_page = "La cuisine française est célèbre dans le monde entier."
    russian_response = (
        "Французская кухня\n\nСтраница рассказывает о знаменитой французской кухне "
        "и её месте в мировой гастрономии."
    )
    svc, _ = make_link_service(scraper_text=french_page, claude_response=russian_response)
    result = await svc.summarize("https://example.com/cuisine", lang="ru")

    assert result.title == "Французская кухня"
    assert "Французская" in result.body or "французской" in result.body


# ── _parse_summary ────────────────────────────────────────────────────────────


async def test_parse_summary_splits_title_and_body() -> None:
    raw = "My Title\n\nThis is the body text."
    result = LinkService._parse_summary(raw, "https://x.com")
    assert result.title == "My Title"
    assert result.body == "This is the body text."


async def test_parse_summary_single_line_uses_as_body_and_url_as_title() -> None:
    """Single-line response with no newline — first line is title, body is same text."""
    raw = "Just one line"
    result = LinkService._parse_summary(raw, "https://x.com")
    assert result.title == "Just one line"
    assert result.body == "Just one line"


async def test_parse_summary_empty_response_falls_back_to_url() -> None:
    raw = ""
    result = LinkService._parse_summary(raw, "https://x.com")
    assert result.title == "https://x.com"


async def test_parse_summary_with_bullet_points_in_body() -> None:
    raw = "Article Title\n\nGreat summary here.\n• Point one\n• Point two"
    result = LinkService._parse_summary(raw, "https://x.com")
    assert result.title == "Article Title"
    assert "• Point one" in result.body
    assert "• Point two" in result.body


async def test_parse_summary_strips_whitespace() -> None:
    raw = "  Title with spaces  \n\n  Body text.  "
    result = LinkService._parse_summary(raw, "https://x.com")
    assert result.title == "Title with spaces"
    assert result.body == "Body text."


# ── scraped_text caching ──────────────────────────────────────────────────────


async def test_save_caches_scraped_text_on_item() -> None:
    """The scraper is called at save time and its output is written to scraped_text."""
    svc, repo = make_link_service(scraper_text="cached page body")
    saved = await svc.save("https://example.com", user_id=1)

    svc._scraper.fetch_text.assert_awaited_once_with("https://example.com")  # type: ignore[attr-defined]
    assert saved.item.scraped_text == "cached page body"


async def test_save_still_succeeds_when_scraper_raises() -> None:
    """Scraper failure must not break save — item is persisted without scraped_text."""
    svc, _ = make_link_service()
    svc._scraper.fetch_text = AsyncMock(side_effect=ScrapingError("timeout"))  # type: ignore[attr-defined]

    saved = await svc.save("https://example.com", user_id=1)

    assert saved.item.scraped_text is None
    # The item was still committed.
    svc._session.commit.assert_awaited()  # type: ignore[attr-defined]


async def test_save_survives_unexpected_scraper_exception() -> None:
    """Any non-ScrapingError from the scraper is swallowed and logged."""
    svc, _ = make_link_service()
    svc._scraper.fetch_text = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[attr-defined]

    saved = await svc.save("https://example.com", user_id=1)

    assert saved.item.scraped_text is None


async def test_save_skips_setting_scraped_text_when_page_is_empty() -> None:
    """Empty scraped text is treated as a cache miss — don't overwrite the column."""
    svc, _ = make_link_service(scraper_text="")
    saved = await svc.save("https://example.com", user_id=1)
    # MagicMock.scraped_text remains the default (None) set in the factory.
    assert saved.item.scraped_text is None


async def test_summarize_uses_cached_scraped_text_and_skips_http() -> None:
    """With a cached Item the scraper must not be invoked."""
    cached = MagicMock(spec=Item)
    cached.scraped_text = "already have this page"
    svc, repo = make_link_service(cached_item=cached)

    item_id = uuid.uuid4()
    result = await svc.summarize("https://example.com", item_id=item_id)

    repo.get_by_id.assert_awaited_once_with(item_id)  # type: ignore[attr-defined]
    svc._scraper.fetch_text.assert_not_awaited()  # type: ignore[attr-defined]
    svc._claude.complete.assert_awaited_once()  # type: ignore[attr-defined]
    sent_prompt = svc._claude.complete.await_args.args[0]  # type: ignore[attr-defined]
    assert "already have this page" in sent_prompt
    assert isinstance(result, LinkSummary)


async def test_summarize_falls_back_to_scraper_when_cache_is_empty() -> None:
    """When the Item exists but has no cached text, fetch fresh and write it back."""
    cached = MagicMock(spec=Item)
    cached.scraped_text = None
    svc, repo = make_link_service(cached_item=cached, scraper_text="fresh body")

    item_id = uuid.uuid4()
    await svc.summarize("https://example.com", item_id=item_id)

    svc._scraper.fetch_text.assert_awaited_once_with("https://example.com")  # type: ignore[attr-defined]
    repo.update_scraped_text.assert_awaited_once_with(item_id, "fresh body")  # type: ignore[attr-defined]


async def test_summarize_falls_back_to_scraper_when_item_missing() -> None:
    """Unknown item_id: fetch fresh text and still try to backfill the cache."""
    svc, repo = make_link_service(cached_item=None, scraper_text="fresh body")

    item_id = uuid.uuid4()
    await svc.summarize("https://example.com", item_id=item_id)

    svc._scraper.fetch_text.assert_awaited_once()  # type: ignore[attr-defined]
    repo.update_scraped_text.assert_awaited_once_with(item_id, "fresh body")  # type: ignore[attr-defined]


async def test_summarize_without_item_id_skips_cache_entirely() -> None:
    """Backwards-compatible path: no item_id means always call the scraper."""
    svc, repo = make_link_service(scraper_text="fresh body")

    await svc.summarize("https://example.com")

    svc._scraper.fetch_text.assert_awaited_once()  # type: ignore[attr-defined]
    repo.get_by_id.assert_not_awaited()  # type: ignore[attr-defined]
    repo.update_scraped_text.assert_not_awaited()  # type: ignore[attr-defined]


async def test_summarize_rolls_back_when_cache_write_fails() -> None:
    """If persisting the cache blows up, the summary still returns successfully."""
    cached = MagicMock(spec=Item)
    cached.scraped_text = None
    svc, repo = make_link_service(cached_item=cached, scraper_text="fresh body")
    repo.update_scraped_text = AsyncMock(side_effect=RuntimeError("DB down"))  # type: ignore[attr-defined]

    item_id = uuid.uuid4()
    result = await svc.summarize("https://example.com", item_id=item_id)

    svc._session.rollback.assert_awaited_once()  # type: ignore[attr-defined]
    assert isinstance(result, LinkSummary)


async def test_summarize_raises_scraping_error_when_no_cache_and_fetch_fails() -> None:
    """Cache miss plus unreachable page propagates ScrapingError as before."""
    cached = MagicMock(spec=Item)
    cached.scraped_text = None
    svc, _ = make_link_service(cached_item=cached)
    svc._scraper.fetch_text = AsyncMock(side_effect=ScrapingError("timeout"))  # type: ignore[attr-defined]

    with pytest.raises(ScrapingError):
        await svc.summarize("https://example.com", item_id=uuid.uuid4())
