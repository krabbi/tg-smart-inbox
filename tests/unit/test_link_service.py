import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from bot.exceptions import ScrapingError
from bot.models.item import Item, ItemType
from bot.repositories.item_repository import ItemRepository
from bot.services.claude_client import ClaudeClient
from bot.services.link_service import LinkService, LinkSummary
from bot.services.scraper import Scraper


def make_link_service(
    *,
    scraper_text: str = "page text",
    claude_response: str = '{"title":"Test","summary":"A summary.","takeaways":["point"]}',
    session: AsyncSession | None = None,
) -> tuple[LinkService, ItemRepository]:
    mock_session = session or MagicMock(spec=AsyncSession)
    mock_session.commit = AsyncMock()

    mock_item = MagicMock(spec=Item)
    mock_item.id = uuid.uuid4()
    mock_item.type = ItemType.link
    mock_item.content = "https://example.com"

    mock_repo = MagicMock(spec=ItemRepository)
    mock_repo.create = AsyncMock(return_value=mock_item)

    mock_scraper = MagicMock(spec=Scraper)
    mock_scraper.fetch_text = AsyncMock(return_value=scraper_text)

    mock_claude = MagicMock(spec=ClaudeClient)
    mock_claude.complete = AsyncMock(return_value=claude_response)

    svc = LinkService(
        session=mock_session,
        item_repo=mock_repo,
        scraper=mock_scraper,
        claude=mock_claude,
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
    svc, _ = make_link_service(session=mock_session)
    await svc.save("https://example.com", user_id=1)
    mock_session.commit.assert_awaited_once()


async def test_save_returns_item() -> None:
    svc, _ = make_link_service()
    item = await svc.save("https://example.com", user_id=1)
    assert item is not None
    assert item.type == ItemType.link


async def test_summarize_calls_scraper_and_claude() -> None:
    svc, _ = make_link_service()
    result = await svc.summarize("https://example.com")
    assert isinstance(result, LinkSummary)
    assert result.title == "Test"
    assert result.summary == "A summary."
    assert result.takeaways == ["point"]
    assert result.url == "https://example.com"


async def test_summarize_raises_scraping_error() -> None:
    svc, _ = make_link_service()
    svc._scraper.fetch_text = AsyncMock(side_effect=ScrapingError("timeout"))  # type: ignore[attr-defined]
    with pytest.raises(ScrapingError):
        await svc.summarize("https://example.com")


async def test_summarize_with_malformed_json_uses_raw_text() -> None:
    svc, _ = make_link_service(claude_response="Not JSON")
    result = await svc.summarize("https://example.com")
    assert result.summary == "Not JSON"
    assert result.title == "https://example.com"


async def test_parse_summary_full_json() -> None:
    raw = '{"title":"Hello","summary":"World.","takeaways":["a","b"]}'
    result = LinkService._parse_summary(raw, "https://x.com")
    assert result.title == "Hello"
    assert result.summary == "World."
    assert result.takeaways == ["a", "b"]


async def test_parse_summary_empty_takeaways() -> None:
    raw = '{"title":"T","summary":"S","takeaways":[]}'
    result = LinkService._parse_summary(raw, "https://x.com")
    assert result.takeaways == []


async def test_parse_summary_strips_markdown_code_fence() -> None:
    raw = '```json\n{"title":"Hello","summary":"World.","takeaways":["a"]}\n```'
    result = LinkService._parse_summary(raw, "https://x.com")
    assert result.title == "Hello"
    assert result.summary == "World."
    assert result.takeaways == ["a"]


async def test_parse_summary_strips_plain_code_fence() -> None:
    raw = '```\n{"title":"T","summary":"S","takeaways":[]}\n```'
    result = LinkService._parse_summary(raw, "https://x.com")
    assert result.title == "T"
    assert result.summary == "S"


async def test_parse_summary_with_preamble_and_code_fence() -> None:
    """Claude sometimes adds a preamble before the JSON block — must still parse correctly."""
    raw = 'Here is the summary:\n```json\n{"title":"T","summary":"S","takeaways":["x"]}\n```'
    result = LinkService._parse_summary(raw, "https://x.com")
    assert result.title == "T"
    assert result.summary == "S"
    assert result.takeaways == ["x"]


async def test_parse_summary_with_preamble_no_fence_uses_fallback() -> None:
    """Preamble without code fence falls back to raw text in summary."""
    raw = "Not valid JSON preamble\nstill not JSON"
    result = LinkService._parse_summary(raw, "https://x.com")
    assert result.title == "https://x.com"
    assert result.summary == raw.strip()


async def test_parse_summary_nested_braces_in_value() -> None:
    """JSON with nested {} in string values must parse correctly (greedy regex)."""
    raw = '```json\n{"title":"A {nested} title","summary":"See {example}.","takeaways":["ok"]}\n```'
    result = LinkService._parse_summary(raw, "https://x.com")
    assert result.title == "A {nested} title"
    assert result.summary == "See {example}."
    assert result.takeaways == ["ok"]
