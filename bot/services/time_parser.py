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
- If the expression is ambiguous (e.g. "за��тра" with no time), default to 09:00 UTC
- If the expression cannot be parsed at all, return {{"error": "unparseable"}}

Time expression: {text}
"""


class TimeParser:
    """Parse natural-language time expressions into datetime objects via Claude."""

    def __init__(self, claude: ClaudeClient) -> None:
        self._claude = claude

    async def parse(self, text: str, now: datetime) -> datetime:
        """Convert a natural language time string to an absolute UTC datetime.

        Raises TimeParseError if the expression cannot be parsed.
        """
        prompt = _PARSE_PROMPT.format(
            now=now.isoformat(),
            text=text,
        )
        try:
            raw = await self._claude.complete(prompt)
            return self._parse_response(raw, text)
        except TimeParseError:
            raise
        except Exception as exc:
            raise TimeParseError(f"Time parsing failed: {exc}") from exc

    @staticmethod
    def _parse_response(raw: str, original_text: str) -> datetime:
        """Parse Claude's JSON response into a datetime.

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
            return datetime.fromisoformat(dt_str)
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            raise TimeParseError(f"Malformed time response: {raw!r}") from exc
