import logging

import httpx

from bot.config import Config
from bot.models.idea import Idea
from bot.models.item import Item

logger = logging.getLogger(__name__)

_VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
_EMBEDDING_MODEL = "voyage-3.5"
_MAX_INPUT_CHARS = 8000


class EmbeddingService:
    """Generate vector embeddings for Items and Ideas via the Voyage AI Embeddings API.

    When the API is unreachable or the key is not configured the service logs and
    returns ``None`` — it never raises, because callers persist records first and
    treat missing embeddings as a transient degradation rather than a fatal error.
    """

    def __init__(self, config: Config) -> None:
        self._dim = config.embedding_dim
        self._api_key = config.voyage_api_key

    async def generate(self, text: str) -> list[float] | None:
        """Call the Voyage AI Embeddings API and return the vector, or ``None`` on failure."""
        if not text or not text.strip():
            return None
        if not self._api_key:
            logger.debug("VOYAGE_API_KEY not configured — embeddings disabled")
            return None
        payload = {"model": _EMBEDDING_MODEL, "input": [text[:_MAX_INPUT_CHARS]]}
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(_VOYAGE_URL, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except Exception:
            logger.exception("Embedding API call failed")
            return None
        return self._parse_vector(data)

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
            if isinstance(response, dict):
                data = response.get("data")
                if isinstance(data, list) and data:
                    first = data[0]
                    vector = first.get("embedding") if isinstance(first, dict) else None
                else:
                    vector = None
            else:
                vector = None

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
