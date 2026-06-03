"""Shared text-processing helpers."""

import re

from bot.models.item import Item, ItemType

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

# Matches common explicit time expressions in Russian and English.
# Used to detect when a task message already carries a time intent.
_TIME_RE = re.compile(
    r"\b("
    r"завтра|послезавтра|сегодня"  # relative days (вчера excluded — past, no future intent)
    r"|через\s+\d+\s*(минут[а-я]*|час[а-я]*|дн[а-яё]*|недел[а-я]*|секунд[а-я]*)"  # "через N ..."
    r"|в\s+\d{1,2}[:.]\d{2}"  # "в 14:00" or "в 14.00"
    r"|\d{1,2}[:.]\d{2}\s*(утра|вечера|дня|ночи)?"  # bare "14:00" or "9:00 утра"
    r"|в\s+(понедельник|вторник|сред[у]?|четверг|пятниц[у]?|суббот[у]?|воскресенье)"  # weekdays
    r"|in\s+\d+\s*(minute|hour|day|second)s?"  # English intervals
    r"|at\s+\d{1,2}(:\d{2})?"  # "at 14" or "at 14:00"
    r"|tomorrow|tonight|today"  # English relative days
    r")",
    re.IGNORECASE,
)


def extract_url(text: str) -> str | None:
    """Return the first HTTP/HTTPS URL found in text, or None."""
    match = _URL_RE.search(text)
    return match.group(0) if match else None


def has_time_expression(text: str) -> bool:
    """Return True if text contains an explicit time or date reference."""
    return bool(_TIME_RE.search(text))


_SUMMARY_INLINE_MAX_CHARS = 200


def format_item_display(item: Item) -> str:
    """Return the user-facing display string for an Item.

    For links: ``{title} ({url})`` when ``Item.title`` is set, otherwise the bare URL.
    For media: ``{description} ({drive_link})`` when ``Item.description`` is set,
    otherwise the bare Drive link.
    For everything else: ``Item.content`` unchanged.

    Callers handle truncation; this helper only chooses what to render.
    """
    if item.type == ItemType.link and getattr(item, "title", None):
        return f"{item.title} ({item.content})"
    if item.type == ItemType.media and item.description:
        return f"{item.description} ({item.content})"
    return item.content


def format_item_display_with_summary(item: Item) -> str:
    """Return the display string for an Item with an inline short summary for links.

    For link items that have a non-empty stored ``summary``, appends a truncated
    version (up to ``_SUMMARY_INLINE_MAX_CHARS`` chars) on a new line below the
    ``{title} ({url})`` header line.  When ``summary`` is absent or blank the
    output is identical to :func:`format_item_display` — no placeholder text.

    Non-link items are rendered exactly as :func:`format_item_display`.
    """
    base = format_item_display(item)
    if item.type != ItemType.link:
        return base
    summary: str | None = getattr(item, "summary", None)
    if not summary or not summary.strip():
        return base
    short = summary.strip()
    if len(short) > _SUMMARY_INLINE_MAX_CHARS:
        short = short[:_SUMMARY_INLINE_MAX_CHARS].rstrip() + "…"
    return f"{base}\n{short}"
