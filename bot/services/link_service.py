import json
import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.item import Item, ItemType
from bot.repositories.item_repository import ItemRepository
from bot.services.claude_client import ClaudeClient
from bot.services.scraper import Scraper

_SUMMARIZE_PROMPT = """\
You are a concise content summarizer. Given the text of a web page, return a JSON object with:
- "title": the page title or best guess (string)
- "summary": 3-5 sentence summary in the same language as the content (string)
- "takeaways": list of 2-3 key points (list of strings)

Respond with JSON only. No explanation outside the JSON.

Page text:
"""


@dataclass(frozen=True)
class LinkSummary:
    """Result of summarizing a link."""

    title: str
    summary: str
    url: str
    takeaways: list[str]


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
        text = await self._scraper.fetch_text(url)
        raw = await self._claude.complete(_SUMMARIZE_PROMPT + text)
        return self._parse_summary(raw, url)

    @staticmethod
    def _parse_summary(raw: str, url: str) -> LinkSummary:
        """Parse Claude's JSON response into a LinkSummary."""
        # Extract JSON from inside code fences when Claude wraps the response
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw.strip(), flags=re.DOTALL)
        text = fenced.group(1).strip() if fenced else raw.strip()
        try:
            data = json.loads(text)
            return LinkSummary(
                title=str(data.get("title", url)),
                summary=str(data.get("summary", "")),
                url=url,
                takeaways=[str(t) for t in data.get("takeaways", [])],
            )
        except (json.JSONDecodeError, TypeError):
            return LinkSummary(title=url, summary=raw.strip(), url=url, takeaways=[])
