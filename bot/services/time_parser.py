import json
import logging
from datetime import datetime

from bot.exceptions import TimeParseError
from bot.services.claude_client import ClaudeClient

logger = logging.getLogger(__name__)

_PARSE_PROMPT = """\
Convert the following time expression to an absolute datetime.
Current datetime (ISO 8601, UTC): {now}

Rules:
- Return JSON only: {{"datetime": "YYYY-MM-DDTHH:MM:SS"}}
- Use UTC timezone
- Any interval is valid, including very short ones like "через 1 минуту" or "через 30 секунд"
- If the expression is ambiguous (e.g. "завтра" with no time), default to 09:00 UTC
- If the expression cannot be parsed at all, return {{"error": "unparseable"}}

Time expression: {text}
"""


class TimeParser:
    """Parse natural-language time expressions into datetime objects via Claude."""

    def __init__(self, claude: ClaudeClient) -> None:
        self._claude = claude

    async def parse(self, text: str, now: datetime) -> datetime:
        """Convert a natural language time string to an absolute UTC datetime.

        Raises TimeParseError if the expression cannot be parsed or is in the past.
        """
        # Normalise now to naive UTC so the prompt is unambiguous for Claude
        now_utc = now.replace(tzinfo=None) if now.tzinfo is not None else now
        prompt = _PARSE_PROMPT.format(
            now=now_utc.isoformat(),
            text=text,
        )
        try:
            raw = await self._claude.complete(prompt)
            remind_at = self._parse_response(raw, text)
        except TimeParseError:
            raise
        except Exception as exc:
            raise TimeParseError(f"Time parsing failed: {exc}") from exc

        # Validate the result is in the future relative to the now we sent Claude.
        # Comparing naive datetimes (both UTC) avoids TypeError from mixed tz-awareness.
        if remind_at <= now_utc:
            raise TimeParseError(f"Parsed time is not in the future for expression {text!r}")
        return remind_at

    @staticmethod
    def _parse_response(raw: str, original_text: str) -> datetime:
        """Parse Claude's JSON response into a naive UTC datetime.

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
            # Normalise to naive UTC: drop timezone info if Claude included it
            return dt.replace(tzinfo=None)
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            raise TimeParseError(f"Malformed time response: {raw!r}") from exc
