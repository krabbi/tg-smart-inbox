from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.item import Item, ItemType
from bot.repositories.item_repository import ItemRepository
from bot.services.claude_client import ClaudeClient
from bot.services.scraper import Scraper

_SUMMARIZE_PROMPT = """\
You are a helpful assistant that summarizes web pages in the same language as the content.

Given the text of a web page, respond with:
- Line 1: the page title (exact title or your best guess)
- Line 2: blank
- Lines 3+: 3-5 sentences explaining what this page is about, written in a natural, \
friendly tone — as if you're telling a friend what they'll find here. \
No bullet points, no headers, no lists. Just flowing prose. \
Complete every sentence — never cut off mid-sentence.

Page text:
"""

_SUMMARIZE_MAX_TOKENS = 512


@dataclass(frozen=True)
class LinkSummary:
    """Result of summarizing a link."""

    title: str
    body: str
    url: str


class LinkService:
    """Handle link saving and on-demand summarization."""

    def __init__(
        self,
        session: AsyncSession,
        item_repo: ItemRepository,
        scraper: Scraper,
        claude: ClaudeClient,
    ) -> None:
        self._session = session
        self._repo = item_repo
        self._scraper = scraper
        self._claude = claude

    async def save(self, url: str, user_id: int) -> Item:
        """Save a link as an Item in the DB and return it."""
        item = await self._repo.create(user_id=user_id, type=ItemType.link, content=url)
        await self._session.commit()
        return item

    async def summarize(self, url: str) -> LinkSummary:
        """Fetch the page and generate a summary using Claude.

        Raises ScrapingError if the page is unreachable.
        Raises ClassificationError if Claude fails.
        """
        page_text = await self._scraper.fetch_text(url)
        raw = await self._claude.complete(
            _SUMMARIZE_PROMPT + page_text, max_tokens=_SUMMARIZE_MAX_TOKENS
        )
        return self._parse_summary(raw, url)

    @staticmethod
    def _parse_summary(raw: str, url: str) -> LinkSummary:
        """Split Claude's plain-text response into title and body."""
        text = raw.strip()
        parts = text.split("\n", 1)
        title = parts[0].strip() if parts else url
        body = parts[1].strip() if len(parts) > 1 else text
        return LinkSummary(title=title or url, body=body, url=url)
