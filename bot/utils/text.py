"""Shared text-processing helpers."""

import re

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

# Matches common explicit time expressions in Russian and English.
# Used to detect when a task message already carries a time intent.
_TIME_RE = re.compile(
    r"\b("
    r"завтра|послезавтра|сегодня|вчера"  # relative days
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
