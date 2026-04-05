import httpx
from bs4 import BeautifulSoup

from bot.exceptions import ScrapingError

_UNWANTED_TAGS = {"script", "style", "nav", "header", "footer", "aside", "advertisement"}
_MAX_TEXT_CHARS = 8000


class Scraper:
    """Fetch a web page and extract its main readable text."""

    async def fetch_text(self, url: str) -> str:
        """Fetch the URL and return cleaned visible text.

        Raises ScrapingError if the page cannot be fetched or is empty.
        """
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
                response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        except Exception as exc:
            raise ScrapingError(f"Failed to fetch {url}: {exc}") from exc

        if response.status_code != 200:
            raise ScrapingError(f"HTTP {response.status_code} for {url}")

        return self._extract_text(response.text)

    def _extract_text(self, html: str) -> str:
        """Strip navigation/ads and return clean body text, capped at MAX_TEXT_CHARS."""
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all(_UNWANTED_TAGS):
            tag.decompose()

        text = soup.get_text(separator=" ", strip=True)
        text = " ".join(text.split())  # collapse whitespace
        return text[:_MAX_TEXT_CHARS]
