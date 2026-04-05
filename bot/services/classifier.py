import enum
import json
import logging
import re

from bot.services.claude_client import ClaudeClient

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

_CLASSIFY_PROMPT = """\
Classify the following message into exactly one category.

Categories:
- task: something the user needs to do, a reminder, an action item (e.g. "buy milk", "call the dentist", "надо позвонить маме")
- idea: a creative idea, project concept, or something to explore later (e.g. "хочу сделать приложение", "idea for a startup")
- note: everything else — a fact, observation, quote, or general information

Respond with JSON only, no explanation:
{"type": "task"} or {"type": "idea"} or {"type": "note"}

Message:
"""


class MessageType(enum.Enum):
    """Possible classification outcomes for an incoming message."""

    LINK = "link"
    TASK = "task"
    NOTE = "note"
    MEDIA = "media"
    IDEA = "idea"


class ClassifierService:
    """Classify incoming messages using fast rules first, Claude API as fallback."""

    def __init__(self, claude: ClaudeClient) -> None:
        self._claude = claude

    async def classify(self, text: str, *, has_media: bool = False) -> MessageType:
        """Return the MessageType for the given message content.

        Short-circuits without an API call for MEDIA and LINK types.
        Falls back to NOTE if Claude returns a malformed response or errors out.
        """
        if has_media:
            return MessageType.MEDIA

        if _URL_RE.search(text):
            return MessageType.LINK

        return await self._classify_with_claude(text)

    async def _classify_with_claude(self, text: str) -> MessageType:
        """Call Claude API to classify text; return NOTE on any failure."""
        try:
            response = await self._claude.complete(_CLASSIFY_PROMPT + text)
            return self._parse_response(response)
        except Exception:
            logger.exception("Classification failed, falling back to NOTE")
            return MessageType.NOTE

    @staticmethod
    def _parse_response(response: str) -> MessageType:
        """Parse Claude's JSON response into a MessageType, defaulting to NOTE."""
        try:
            data = json.loads(response.strip())
            type_str = data.get("type", "").lower()
            mapping = {
                "task": MessageType.TASK,
                "idea": MessageType.IDEA,
                "note": MessageType.NOTE,
            }
            return mapping.get(type_str, MessageType.NOTE)
        except (json.JSONDecodeError, AttributeError):
            return MessageType.NOTE
