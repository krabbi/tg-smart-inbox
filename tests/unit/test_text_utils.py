"""Tests for ``bot/utils/text.py`` — URL extraction, time detection, item display."""

from unittest.mock import MagicMock

from bot.models.item import Item, ItemType
from bot.utils.text import extract_url, format_item_display, has_time_expression

# ── extract_url ───────────────────────────────────────────────────────────────


def test_extract_url_finds_https() -> None:
    assert extract_url("see https://example.com here") == "https://example.com"


def test_extract_url_finds_http() -> None:
    assert extract_url("http://example.org") == "http://example.org"


def test_extract_url_returns_none_when_missing() -> None:
    assert extract_url("just plain text") is None


# ── has_time_expression ──────────────────────────────────────────────────────


def test_has_time_expression_detects_relative_day() -> None:
    assert has_time_expression("сделать завтра") is True


def test_has_time_expression_returns_false_for_plain_task() -> None:
    assert has_time_expression("купить молоко") is False


# ── format_item_display ──────────────────────────────────────────────────────


def _make_item(
    *,
    item_type: ItemType,
    content: str,
    title: str | None = None,
    description: str | None = None,
) -> MagicMock:
    item = MagicMock(spec=Item)
    item.type = item_type
    item.content = content
    item.title = title
    item.description = description
    return item


def test_format_item_display_link_with_title_uses_parenthesis() -> None:
    """Link with a saved title shows ``{title} ({url})``."""
    item = _make_item(
        item_type=ItemType.link,
        content="https://example.com/article",
        title="Cool Article",
    )
    assert format_item_display(item) == "Cool Article (https://example.com/article)"


def test_format_item_display_link_without_title_returns_bare_url() -> None:
    """Link without a stored title falls back to the raw URL."""
    item = _make_item(item_type=ItemType.link, content="https://example.com/raw", title=None)
    assert format_item_display(item) == "https://example.com/raw"


def test_format_item_display_link_with_empty_title_returns_bare_url() -> None:
    """An empty string title is treated the same as ``None``."""
    item = _make_item(item_type=ItemType.link, content="https://example.com", title="")
    assert format_item_display(item) == "https://example.com"


def test_format_item_display_media_with_description_shows_drive_link() -> None:
    """Media with a Vision description renders as ``{description} ({drive_link})``."""
    drive_link = "https://drive.google.com/file/d/abc"
    item = _make_item(
        item_type=ItemType.media,
        content=drive_link,
        description="Receipt from supermarket",
    )
    assert format_item_display(item) == f"Receipt from supermarket ({drive_link})"


def test_format_item_display_media_without_description_returns_bare_link() -> None:
    """Media without a description falls back to the bare Drive link."""
    drive_link = "https://drive.google.com/file/d/xyz"
    item = _make_item(item_type=ItemType.media, content=drive_link, description=None)
    assert format_item_display(item) == drive_link


def test_format_item_display_note_returns_content_unchanged() -> None:
    """Notes always show their content as-is (no parenthetical, no fallback)."""
    item = _make_item(item_type=ItemType.note, content="quick reminder to self")
    assert format_item_display(item) == "quick reminder to self"


def test_format_item_display_task_returns_content_unchanged() -> None:
    """Tasks always show their content; ``title`` is irrelevant for non-link types."""
    item = _make_item(item_type=ItemType.task, content="buy milk", title="ignored title")
    assert format_item_display(item) == "buy milk"


def test_format_item_display_idea_returns_content_unchanged() -> None:
    """Ideas show their content; the parenthetical pattern is reserved for link/media."""
    item = _make_item(item_type=ItemType.idea, content="bot for expense tracking")
    assert format_item_display(item) == "bot for expense tracking"
