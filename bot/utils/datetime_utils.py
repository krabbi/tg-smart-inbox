"""Datetime formatting helpers for user-facing messages."""

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

_DATETIME_FORMAT = "%d.%m.%Y %H:%M"


def format_remind_at(dt: datetime, user_tz: str) -> str:
    """Format a UTC datetime as local time in ``user_tz`` for display to the user.

    Returns ``"DD.MM.YYYY HH:MM <ZONE>"`` where ``<ZONE>`` is the timezone abbreviation
    (e.g. ``MSK``) when the platform exposes one, or the IANA name otherwise
    (e.g. ``Asia/Kabul`` for zones without a short alphabetic abbreviation).

    ``dt`` may be naive (treated as UTC, matching legacy behaviour) or timezone-aware.
    An invalid ``user_tz`` falls back silently to UTC.
    """
    try:
        tz = ZoneInfo(user_tz)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("Invalid user_tz %r, falling back to UTC", user_tz)
        tz = ZoneInfo("UTC")
        user_tz = "UTC"

    aware = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt
    local = aware.astimezone(tz)

    # Prefer the short abbreviation (e.g. "MSK", "EDT") when the zone exposes one.
    # zoneinfo returns numeric strings like "+0430" for zones without an alphabetic
    # abbreviation — in that case fall back to the IANA name to keep the output
    # readable.
    abbr = local.tzname() or ""
    label = abbr if abbr and abbr[0].isalpha() else user_tz

    return f"{local.strftime(_DATETIME_FORMAT)} {label}"
