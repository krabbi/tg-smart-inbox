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


# ── title extraction ─────────────────────────────────────────────────────────


def test_extract_title_prefers_og_title_over_title_tag() -> None:
    """og:title is curated by the page author and wins over the bare <title>."""
    html = """
    <html><head>
      <title>Site Name — Long Suffix We Don't Want</title>
      <meta property="og:title" content="Clean Article Headline">
    </head><body><p>x</p></body></html>
    """
    scraper = Scraper()
    assert scraper._extract_title(html) == "Clean Article Headline"


def test_extract_title_falls_back_to_title_tag() -> None:
    """When og:title is missing, the contents of <title> are used."""
    html = "<html><head><title>Plain Page Title</title></head><body><p>x</p></body></html>"
    scraper = Scraper()
    assert scraper._extract_title(html) == "Plain Page Title"


def test_extract_title_returns_none_when_neither_present() -> None:
    """No og:title, no <title> → None (callers persist the URL alone)."""
    html = "<html><body><p>just a body</p></body></html>"
    scraper = Scraper()
    assert scraper._extract_title(html) is None


def test_extract_title_returns_none_for_empty_title_tag() -> None:
    """An empty <title></title> is treated the same as a missing tag."""
    html = "<html><head><title></title></head><body><p>x</p></body></html>"
    scraper = Scraper()
    assert scraper._extract_title(html) is None


def test_extract_title_collapses_whitespace_and_caps_length() -> None:
    """Long, whitespace-noisy titles are collapsed and capped at 500 chars."""
    long_title = "Word " * 200
    html = f"<html><head><title>\n  {long_title}  </title></head><body></body></html>"
    scraper = Scraper()
    result = scraper._extract_title(html)
    assert result is not None
    assert len(result) <= 500
    assert "  " not in result


def test_extract_title_ignores_og_title_with_blank_content() -> None:
    """og:title with blank content falls through to <title>."""
    html = """
    <html><head>
      <meta property="og:title" content="   ">
      <title>Real Title</title>
    </head><body></body></html>
    """
    scraper = Scraper()
    assert scraper._extract_title(html) == "Real Title"


async def test_fetch_returns_text_and_title() -> None:
    """``fetch`` returns a ScrapedPage carrying both the text and the title."""
    html = """
    <html><head><meta property="og:title" content="Hello"></head>
    <body><p>The body content.</p></body></html>
    """
    scraper = Scraper()
    mock_response = make_response(200, html)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        page = await scraper.fetch("https://example.com")

    assert page.title == "Hello"
    assert "The body content." in page.text


async def test_fetch_propagates_scraping_error_on_http_failure() -> None:
    """Network failures still raise ScrapingError for the caller to handle."""
    scraper = Scraper()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("connection refused"))

        with pytest.raises(ScrapingError):
            await scraper.fetch("https://example.com")


async def test_fetch_returns_none_title_when_page_lacks_title() -> None:
    """A page without a <title> or og:title yields ScrapedPage(text=..., title=None)."""
    html = "<html><body><p>Body only.</p></body></html>"
    scraper = Scraper()
    mock_response = make_response(200, html)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        page = await scraper.fetch("https://example.com")

    assert page.title is None
    assert "Body only." in page.text
