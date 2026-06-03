"""Tests for ``bot/utils/text.py`` — URL extraction, time detection, item display."""

from unittest.mock import MagicMock

from bot.models.item import Item, ItemType
from bot.utils.text import (
    _SUMMARY_INLINE_MAX_CHARS,
    extract_url,
    format_item_display,
    format_item_display_with_summary,
    has_time_expression,
)

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
    summary: str | None = None,
) -> MagicMock:
    item = MagicMock(spec=Item)
    item.type = item_type
    item.content = content
    item.title = title
    item.description = description
    item.summary = summary
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


# ── format_item_display_with_summary ─────────────────────────────────────────


def test_format_item_display_with_summary_link_with_summary_appends_body() -> None:
    """Link with stored summary shows title+url on line 1 and truncated summary on line 2."""
    item = _make_item(
        item_type=ItemType.link,
        content="https://example.com/article",
        title="Cool Article",
        summary="This page talks about something interesting.",
    )
    result = format_item_display_with_summary(item)
    assert result == (
        "Cool Article (https://example.com/article)\nThis page talks about something interesting."
    )


def test_format_item_display_with_summary_link_no_summary_falls_back() -> None:
    """Link without a stored summary renders the same as format_item_display."""
    item = _make_item(
        item_type=ItemType.link,
        content="https://example.com/raw",
        title="Raw Link",
        summary=None,
    )
    assert format_item_display_with_summary(item) == "Raw Link (https://example.com/raw)"


def test_format_item_display_with_summary_link_empty_summary_falls_back() -> None:
    """An empty/whitespace summary is treated as absent — no extra line appended."""
    item = _make_item(
        item_type=ItemType.link,
        content="https://example.com",
        title="Title",
        summary="   ",
    )
    assert format_item_display_with_summary(item) == "Title (https://example.com)"


def test_format_item_display_with_summary_truncates_long_summary() -> None:
    """Summaries longer than the cap are truncated with an ellipsis."""
    long_summary = "A" * (_SUMMARY_INLINE_MAX_CHARS + 50)
    item = _make_item(
        item_type=ItemType.link,
        content="https://example.com",
        title="T",
        summary=long_summary,
    )
    result = format_item_display_with_summary(item)
    lines = result.split("\n", 1)
    assert len(lines) == 2
    assert lines[1].endswith("…")
    assert len(lines[1]) <= _SUMMARY_INLINE_MAX_CHARS + 1  # +1 for the ellipsis char


def test_format_item_display_with_summary_summary_at_exact_cap_not_truncated() -> None:
    """A summary exactly at the cap length is not truncated."""
    exact_summary = "B" * _SUMMARY_INLINE_MAX_CHARS
    item = _make_item(
        item_type=ItemType.link,
        content="https://example.com",
        title="T",
        summary=exact_summary,
    )
    result = format_item_display_with_summary(item)
    lines = result.split("\n", 1)
    assert lines[1] == exact_summary
    assert not lines[1].endswith("…")


def test_format_item_display_with_summary_non_link_ignores_summary() -> None:
    """Non-link types are rendered identically to format_item_display regardless of summary."""
    task = _make_item(
        item_type=ItemType.task,
        content="buy milk",
        summary="This would be strange on a task.",
    )
    assert format_item_display_with_summary(task) == "buy milk"


def test_format_item_display_with_summary_note_ignores_summary() -> None:
    """Notes are rendered without a summary line even when one is set."""
    note = _make_item(
        item_type=ItemType.note,
        content="my note",
        summary="should not appear",
    )
    assert format_item_display_with_summary(note) == "my note"
