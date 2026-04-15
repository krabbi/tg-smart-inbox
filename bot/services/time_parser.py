import json
import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bot.exceptions import TimeParseError
from bot.services.claude_client import ClaudeClient

logger = logging.getLogger(__name__)

_PARSE_PROMPT = """\
Convert the following time expression to an absolute datetime.
Current datetime (ISO 8601, local time in timezone {tz}): {now}

Rules:
- Return JSON only: {{"datetime": "YYYY-MM-DDTHH:MM:SS"}}
- Interpret the expression as local time in timezone {tz}
- Any interval is valid, including very short ones like "через 1 минуту" or "через 30 секунд"
- If the expression is ambiguous (e.g. "завтра" with no time), default to 09:00 local time
- If the expression cannot be parsed at all, return {{"error": "unparseable"}}

Time expression: {text}
"""


class TimeParser:
    """Parse natural-language time expressions into datetime objects via Claude."""

    def __init__(self, claude: ClaudeClient) -> None:
        self._claude = claude

    async def parse(self, text: str, now: datetime, user_tz: str = "UTC") -> datetime:
        """Convert a natural language time string to an absolute datetime.

        Parses the text as local time in ``user_tz`` (IANA tz name) and returns:
        * naive UTC datetime when ``user_tz == "UTC"`` (backward-compatible behaviour);
        * aware UTC datetime otherwise.

        Raises TimeParseError if the expression cannot be parsed or is in the past.
        """
        try:
            tz = ZoneInfo(user_tz)
        except (ZoneInfoNotFoundError, ValueError):
            logger.warning("Invalid user_tz %r, falling back to UTC", user_tz)
            tz = ZoneInfo("UTC")
            user_tz = "UTC"

        # Convert ``now`` to local time in the user's timezone so Claude receives
        # the prompt in the same reference frame as the user's expression.
        now_aware = now.replace(tzinfo=UTC) if now.tzinfo is None else now
        now_local = now_aware.astimezone(tz)
        now_local_naive = now_local.replace(tzinfo=None)

        prompt = _PARSE_PROMPT.format(
            now=now_local_naive.isoformat(),
            tz=user_tz,
            text=text,
        )
        try:
            raw = await self._claude.complete(prompt)
            remind_at_naive = self._parse_response(raw, text)
        except TimeParseError:
            raise
        except Exception as exc:
            raise TimeParseError(f"Time parsing failed: {exc}") from exc

        # Interpret Claude's naive datetime as local time in ``tz``
        remind_at_local = remind_at_naive.replace(tzinfo=tz)
        remind_at_utc = remind_at_local.astimezone(UTC)

        # Validate the result is in the future (compare aware datetimes)
        if remind_at_utc <= now_aware:
            raise TimeParseError(f"Parsed time is not in the future for expression {text!r}")

        # Backward compatibility: callers that don't care about tzinfo get a naive UTC
        # datetime when ``user_tz`` is "UTC", matching the old behaviour.
        if user_tz == "UTC":
            return remind_at_utc.replace(tzinfo=None)
        return remind_at_utc

    @staticmethod
    def _parse_response(raw: str, original_text: str) -> datetime:
        """Parse Claude's JSON response into a naive datetime (caller applies tzinfo).

        Strips markdown code fences (```json ... ```) that Claude sometimes wraps around JSON.
        """
        cleaned = raw.strip()
        # Remove optional ```json ... ``` or ``` ... ``` fences
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()
        try:
            data = json.loads(cleaned)
            if "error" in data:
                raise TimeParseError(f"Cannot parse time: {original_text!r}")
            dt_str = data["datetime"]
            dt = datetime.fromisoformat(dt_str)
            # Normalise to naive: drop any timezone info Claude may have added
            return dt.replace(tzinfo=None)
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            raise TimeParseError(f"Malformed time response: {raw!r}") from exc
