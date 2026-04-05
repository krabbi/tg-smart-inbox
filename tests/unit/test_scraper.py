from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.exceptions import ScrapingError
from bot.services.scraper import Scraper


def make_response(status_code: int, text: str) -> MagicMock:
    """Create a mock httpx response."""
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    return r


async def test_fetch_text_returns_clean_text() -> None:
    html = """
    <html><body>
      <nav>Nav stuff</nav>
      <p>Main content here.</p>
      <script>alert('ads')</script>
      <footer>Footer</footer>
    </body></html>
    """
    scraper = Scraper()
    mock_response = make_response(200, html)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await scraper.fetch_text("https://example.com")

    assert "Main content here." in result
    assert "Nav stuff" not in result
    assert "alert" not in result
    assert "Footer" not in result


async def test_non_200_raises_scraping_error() -> None:
    scraper = Scraper()
    mock_response = make_response(404, "Not Found")

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with pytest.raises(ScrapingError, match="HTTP 404"):
            await scraper.fetch_text("https://example.com/missing")


async def test_network_error_raises_scraping_error() -> None:
    scraper = Scraper()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("connection refused"))

        with pytest.raises(ScrapingError, match="Failed to fetch"):
            await scraper.fetch_text("https://example.com")


async def test_text_is_capped_at_max_chars() -> None:
    long_html = f"<html><body><p>{'x' * 10000}</p></body></html>"
    scraper = Scraper()
    mock_response = make_response(200, long_html)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await scraper.fetch_text("https://example.com")

    assert len(result) <= 8000


def test_extract_text_strips_scripts_and_nav() -> None:
    html = "<html><body><nav>Nav</nav><script>js()</script><p>Content</p></body></html>"
    scraper = Scraper()
    result = scraper._extract_text(html)
    assert "Content" in result
    assert "Nav" not in result
    assert "js()" not in result
