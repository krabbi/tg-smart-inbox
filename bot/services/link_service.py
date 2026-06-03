import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from bot.exceptions import ScrapingError
from bot.i18n import DEFAULT_LANGUAGE, language_name
from bot.models.item import Item, ItemType
from bot.repositories.item_repository import ItemRepository
from bot.services.claude_client import ClaudeClient
from bot.services.embedding_service import EmbeddingService
from bot.services.scraper import ScrapedPage, Scraper

logger = logging.getLogger(__name__)


class _Unset:
    """Sentinel type used to distinguish 'not yet fetched' from 'fetched and got None'."""


_UNSET = _Unset()

_SUMMARIZE_PROMPT = """\
You are a helpful assistant that summarizes web pages for a {language}-speaking user.

CRITICAL LANGUAGE REQUIREMENT: Your entire response MUST be written in {language}, \
regardless of the original language of the page. This applies to the title, the summary \
body, and any key takeaways. If the page is in a different language — translate \
everything into natural, fluent {language}. Never leave any part of the response in the \
source language.

Given the text of a web page, respond with:
- Line 1: the page title in {language} (translated or rendered naturally)
- Line 2: blank
- Lines 3+: 3-5 sentences in {language} explaining what this page is about, written in \
a natural, friendly tone — as if you're telling a friend what they'll find here. \
No bullet points, no headers, no lists. Just flowing {language} prose. \
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


@dataclass(frozen=True)
class SavedLink:
    """Result of saving a link — the persisted Item plus indexing status."""

    item: Item
    indexed: bool


class LinkService:
    """Handle link saving and on-demand summarization."""

    def __init__(
        self,
        session: AsyncSession,
        item_repo: ItemRepository,
        scraper: Scraper,
        claude: ClaudeClient,
        embedding_service: EmbeddingService | None = None,
    ) -> None:
        self._session = session
        self._repo = item_repo
        self._scraper = scraper
        self._claude = claude
        self._embedding = embedding_service

    async def save(self, url: str, user_id: int, lang: str = DEFAULT_LANGUAGE) -> SavedLink:
        """Save a link as an Item, cache the page text/title/summary, and attempt to index it.

        The save itself always succeeds.  Scraping and summary generation are both
        best-effort: failures are logged and the link is still persisted without the
        optional fields.  The ``lang`` argument controls the language of the generated
        summary (matches the user's interface language).
        """
        item = await self._repo.create(user_id=user_id, type=ItemType.link, content=url)
        # Populate the cache before the first commit so all fields land in one write.
        page = await self._try_scrape(url)
        if page is not None:
            if page.text:
                item.scraped_text = page.text
            if page.title:
                item.title = page.title

        # Generate and persist the AI summary at save time so reminder notifications
        # can show it inline without an extra Claude call.  Failures are silenced so
        # they never prevent the link from being saved.
        if item.scraped_text:
            summary = await self._try_summarize(url, item.scraped_text, lang)
            if summary is not None:
                item.summary = summary.body

        await self._session.commit()

        indexed = await self._try_index(item)
        return SavedLink(item=item, indexed=indexed)

    async def _try_scrape(self, url: str) -> ScrapedPage | None:
        """Fetch the page text and title for caching; return ``None`` on any failure."""
        try:
            return await self._scraper.fetch(url)
        except ScrapingError as exc:
            logger.warning("Scraping failed for %s: %s", url, exc)
            return None
        except Exception:
            logger.exception("Unexpected error scraping %s", url)
            return None

    async def _try_summarize(self, url: str, page_text: str, lang: str) -> "LinkSummary | None":
        """Generate a summary from already-scraped text; return None on any failure."""
        try:
            prompt = _SUMMARIZE_PROMPT.format(language=language_name(lang)) + page_text
            raw = await self._claude.complete(prompt, max_tokens=_SUMMARIZE_MAX_TOKENS)
            return self._parse_summary(raw, url)
        except Exception:
            logger.exception("Summary generation failed for %s at save time", url)
            return None

    async def _try_index(self, item: Item) -> bool:
        """Generate and store the item's embedding; return True on success, False otherwise."""
        if self._embedding is None:
            return False
        try:
            vector = await self._embedding.generate_for_item(item)
        except Exception:
            logger.exception("Embedding generation raised for item %s", item.id)
            return False
        if vector is None:
            return False
        try:
            await self._repo.update_embedding(item.id, vector)
            await self._session.commit()
        except Exception:
            logger.exception("Failed to persist embedding for item %s", item.id)
            await self._session.rollback()
            return False
        return True

    async def summarize(
        self,
        url: str,
        user_id: int,
        item_id: uuid.UUID | None = None,
        lang: str = DEFAULT_LANGUAGE,
    ) -> LinkSummary:
        """Return a summary for the given URL, preferring the stored summary.

        When ``item_id`` is provided and the Item belongs to ``user_id`` and already
        has a stored ``summary``, it is returned immediately — no Claude call and no
        HTTP request.

        When no stored summary is available the page text is resolved (from
        ``scraped_text`` cache or via a fresh HTTP fetch) and Claude generates the
        summary on demand.  The cached ``scraped_text`` path avoids HTTP when present;
        fresh text is written back to the cache for future calls.

        The ``lang`` argument is interpolated into the Claude prompt so the title and
        body are returned in the user's interface language (``"ru"`` or ``"en"``).

        Raises ScrapingError if the page is unreachable and no cached text is available.
        Raises ClassificationError if Claude fails.
        """
        # Fetch the item once up front when an item_id is given so we can check
        # both the stored summary and the scraped_text cache without two DB round trips.
        # _UNSET distinguishes "not yet fetched" from "fetched and got None".
        prefetched: Item | None | _Unset = _UNSET
        if item_id is not None:
            prefetched = await self._repo.get_by_id_for_user(item_id, user_id)
            if prefetched is not None and prefetched.summary and prefetched.summary.strip():
                # Stored summary available — return immediately, no Claude call needed.
                stored_title = prefetched.title or url
                return LinkSummary(title=stored_title, body=prefetched.summary, url=url)

        page_text = await self._resolve_page_text(url, item_id, user_id, prefetched=prefetched)
        prompt = _SUMMARIZE_PROMPT.format(language=language_name(lang)) + page_text
        raw = await self._claude.complete(prompt, max_tokens=_SUMMARIZE_MAX_TOKENS)
        return self._parse_summary(raw, url)

    async def _resolve_page_text(
        self,
        url: str,
        item_id: uuid.UUID | None,
        user_id: int,
        prefetched: "Item | None | _Unset" = _UNSET,
    ) -> str:
        """Return cached ``scraped_text`` for the user's Item, or scrape and cache it.

        Cache reads and writes are scoped to ``user_id`` so a malicious callback
        carrying another user's item_id cannot leak that user's cached text or
        overwrite their cache with attacker-controlled content.

        Pass ``prefetched`` when the caller has already loaded the Item to avoid a
        redundant ``get_by_id_for_user`` round trip.  Use the ``_UNSET`` sentinel
        (the default) when no prior fetch was attempted.
        """
        if item_id is not None:
            if isinstance(prefetched, _Unset):
                item: Item | None = await self._repo.get_by_id_for_user(item_id, user_id)
            else:
                item = prefetched
            if item is not None and item.scraped_text:
                return item.scraped_text

        page_text = await self._scraper.fetch_text(url)

        # Backfill the cache so subsequent summaries for the same Item hit memory.
        # ``update_scraped_text_for_user`` silently returns False for foreign IDs,
        # which means we never write a value into another user's row.
        if item_id is not None:
            try:
                await self._repo.update_scraped_text_for_user(item_id, user_id, page_text)
                await self._session.commit()
            except Exception:
                logger.exception("Failed to cache scraped_text for item %s", item_id)
                await self._session.rollback()

        return page_text

    @staticmethod
    def _parse_summary(raw: str, url: str) -> LinkSummary:
        """Split Claude's plain-text response into title and body."""
        text = raw.strip()
        parts = text.split("\n", 1)
        title = parts[0].strip() if parts else url
        body = parts[1].strip() if len(parts) > 1 else text
        return LinkSummary(title=title or url, body=body, url=url)
