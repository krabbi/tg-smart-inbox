import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from bot.exceptions import ScrapingError
from bot.models.item import Item, ItemType
from bot.repositories.item_repository import ItemRepository
from bot.services.claude_client import ClaudeClient
from bot.services.link_service import _SUMMARIZE_PROMPT, LinkService, LinkSummary
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
    assert result.title == "Как печь хлеб"
    assert "просто" in result.body
    assert result.url == "https://example.com"


async def test_summarize_raises_scraping_error() -> None:
    svc, _ = make_link_service()
    svc._scraper.fetch_text = AsyncMock(side_effect=ScrapingError("timeout"))  # type: ignore[attr-defined]
    with pytest.raises(ScrapingError):
        await svc.summarize("https://example.com")


# ── language requirement ─────────────────────────────────────────────────────


async def test_summarize_prompt_requires_russian_output() -> None:
    """Prompt must explicitly instruct Claude to respond in Russian."""
    assert "Russian" in _SUMMARIZE_PROMPT
    # Must cover the case when the source page is in another language.
    assert "regardless of the original language" in _SUMMARIZE_PROMPT


async def test_summarize_sends_russian_instruction_to_claude() -> None:
    """The actual prompt passed to Claude.complete must carry the Russian requirement."""
    english_page = (
        "Bread baking is a wonderful hobby. You need flour, water, salt and yeast. "
        "Mix, knead, proof, bake. Enjoy fresh bread at home."
    )
    svc, _ = make_link_service(
        scraper_text=english_page,
        claude_response="Как печь хлеб\n\nСтатья о домашней выпечке хлеба.",
    )
    result = await svc.summarize("https://example.com/bread")

    # The prompt sent to Claude must include the Russian-language requirement.
    svc._claude.complete.assert_awaited_once()  # type: ignore[attr-defined]
    sent_prompt = svc._claude.complete.await_args.args[0]  # type: ignore[attr-defined]
    assert "Russian" in sent_prompt
    assert "regardless of the original language" in sent_prompt
    assert english_page in sent_prompt

    # Title and body come back in Russian (as Claude was instructed to translate).
    assert result.title == "Как печь хлеб"
    assert "выпечке" in result.body


async def test_summarize_returns_russian_for_non_english_source() -> None:
    """Summary for a page in any foreign language is returned in Russian."""
    french_page = "La cuisine française est célèbre dans le monde entier."
    russian_response = (
        "Французская кухня\n\nСтраница рассказывает о знаменитой французской кухне "
        "и её месте в мировой гастрономии."
    )
    svc, _ = make_link_service(scraper_text=french_page, claude_response=russian_response)
    result = await svc.summarize("https://example.com/cuisine")

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
