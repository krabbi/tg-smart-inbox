from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from bot.exceptions import ScrapingError

_UNWANTED_TAGS = {"script", "style", "nav", "header", "footer", "aside", "advertisement"}
_MAX_TEXT_CHARS = 8000
_MAX_TITLE_CHARS = 500


@dataclass(frozen=True)
class ScrapedPage:
    """Result of scraping a web page — its readable text plus the page title."""

    text: str
    title: str | None


class Scraper:
    """Fetch a web page and extract its main readable text."""

    async def fetch(self, url: str) -> ScrapedPage:
        """Fetch the URL and return cleaned text plus the extracted page title.

        Raises ScrapingError if the page cannot be fetched. Returned ``title``
        is ``None`` when neither ``og:title`` nor ``<title>`` is found; ``text``
        may be empty for pages that contain no readable body.
        """
        html = await self._fetch_html(url)
        return ScrapedPage(text=self._extract_text(html), title=self._extract_title(html))

    async def fetch_text(self, url: str) -> str:
        """Fetch the URL and return cleaned visible text.

        Raises ScrapingError if the page cannot be fetched or is empty.
        """
        html = await self._fetch_html(url)
        return self._extract_text(html)

    async def _fetch_html(self, url: str) -> str:
        """Download the raw HTML of ``url``; raise ``ScrapingError`` on any HTTP failure."""
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
                response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        except Exception as exc:
            raise ScrapingError(f"Failed to fetch {url}: {exc}") from exc

        if response.status_code != 200:
            raise ScrapingError(f"HTTP {response.status_code} for {url}")

        return response.text

    def _extract_text(self, html: str) -> str:
        """Strip navigation/ads and return clean body text, capped at MAX_TEXT_CHARS."""
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all(_UNWANTED_TAGS):
            tag.decompose()

        text = soup.get_text(separator=" ", strip=True)
        text = " ".join(text.split())  # collapse whitespace
        return text[:_MAX_TEXT_CHARS]

    def _extract_title(self, html: str) -> str | None:
        """Return ``og:title`` (preferred) or ``<title>``; ``None`` if neither is present.

        The result is whitespace-collapsed and capped at ``_MAX_TITLE_CHARS``.
        """
        soup = BeautifulSoup(html, "html.parser")

        # Prefer Open Graph title — it's curated by the author and usually cleaner
        # than the raw <title> (which often carries site-wide suffixes).
        og = soup.find("meta", attrs={"property": "og:title"})
        if og is not None:
            content = og.get("content")
            if isinstance(content, str):
                cleaned = " ".join(content.split())
                if cleaned:
                    return cleaned[:_MAX_TITLE_CHARS]

        title_tag = soup.find("title")
        if title_tag is not None:
            text = title_tag.get_text(strip=True)
            cleaned = " ".join(text.split())
            if cleaned:
                return cleaned[:_MAX_TITLE_CHARS]

        return None
