import logging

import anthropic

from bot.config import Config
from bot.models.idea import Idea
from bot.models.item import Item

logger = logging.getLogger(__name__)

_EMBEDDING_MODEL = "claude-embedding-1"
_EMBEDDING_PATH = "/v1/embeddings"
_MAX_INPUT_CHARS = 8000


class EmbeddingService:
    """Generate vector embeddings for Items and Ideas via the Anthropic Embeddings API.

    Anthropic's embeddings endpoint is reached through the SDK's low-level HTTP
    client (`self._client.post`). When the API is unreachable or returns an
    unexpected shape the service logs and returns ``None`` — it never raises,
    because callers persist records first and treat missing embeddings as a
    transient degradation rather than a fatal error.
    """

    def __init__(self, config: Config) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)
        self._dim = config.embedding_dim

    async def generate(self, text: str) -> list[float] | None:
        """Call the Anthropic Embeddings API and return the vector, or ``None`` on failure."""
        if not text or not text.strip():
            return None
        payload = {"model": _EMBEDDING_MODEL, "input": text[:_MAX_INPUT_CHARS]}
        try:
            response = await self._client.post(
                _EMBEDDING_PATH,
                body=payload,
                cast_to=dict,
            )
        except Exception:
            logger.exception("Embedding API call failed")
            return None
        return self._parse_vector(response)

    async def generate_for_item(self, item: Item) -> list[float] | None:
        """Build the searchable text for an Item and return its embedding, or ``None``."""
        text = self._item_text(item)
        if not text:
            return None
        return await self.generate(text)

    async def generate_for_idea(self, idea: Idea) -> list[float] | None:
        """Build the searchable text for an Idea (content + tags) and return its embedding."""
        text = self._idea_text(idea)
        if not text:
            return None
        return await self.generate(text)

    @staticmethod
    def _item_text(item: Item) -> str:
        """Concatenate the item's searchable fields: content, description, scraped_text."""
        parts: list[str] = []
        if item.content:
            parts.append(item.content)
        if item.description:
            parts.append(item.description)
        if item.scraped_text:
            parts.append(item.scraped_text)
        return "\n\n".join(parts).strip()

    @staticmethod
    def _idea_text(idea: Idea) -> str:
        """Blend the parent item's content with the idea's tags for idea-level search."""
        parts: list[str] = []
        # Idea.item is a SQLAlchemy relationship — may be None in tests with bare mocks.
        item = getattr(idea, "item", None)
        if item is not None and getattr(item, "content", None):
            parts.append(item.content)
        if idea.tags:
            parts.append("Теги: " + ", ".join(idea.tags))
        return "\n\n".join(parts).strip()

    def _parse_vector(self, response: object) -> list[float] | None:
        """Extract a float vector from the API response; return ``None`` on shape mismatch."""
        try:
            # Anthropic embeddings responses follow OpenAI's shape:
            # {"data": [{"embedding": [...]}], ...}
            if isinstance(response, dict):
                data = response.get("data")
                if isinstance(data, list) and data:
                    first = data[0]
                    if isinstance(first, dict):
                        vector = first.get("embedding")
                    else:
                        vector = getattr(first, "embedding", None)
                else:
                    vector = response.get("embedding")
            else:
                vector = getattr(response, "embedding", None)

            if not isinstance(vector, list):
                logger.warning("Embedding API returned unexpected payload shape")
                return None
            result = [float(x) for x in vector]
        except (TypeError, ValueError):
            logger.exception("Failed to parse embedding vector from response")
            return None

        if len(result) != self._dim:
            logger.warning(
                "Embedding dimension mismatch: got %d, expected %d", len(result), self._dim
            )
            return None
        return result
