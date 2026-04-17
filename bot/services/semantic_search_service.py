import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from bot.exceptions import SemanticSearchUnavailableError
from bot.repositories.idea_repository import IdeaRepository
from bot.repositories.item_repository import ItemRepository
from bot.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)

_PREVIEW_CHARS = 200

ResultKind = Literal["item", "idea"]


@dataclass(frozen=True)
class SearchResult:
    """A single semantic search hit from either the items or the ideas table."""

    id: uuid.UUID
    type: ResultKind
    title: str
    preview_text: str
    score: float
    created_at: datetime


class SemanticSearchService:
    """Run vector similarity searches over the user's Items and Ideas."""

    def __init__(
        self,
        embedding_service: EmbeddingService,
        item_repo: ItemRepository,
        idea_repo: IdeaRepository,
    ) -> None:
        self._embedding = embedding_service
        self._item_repo = item_repo
        self._idea_repo = idea_repo

    async def search(
        self, user_id: int, query: str, limit: int = 20, offset: int = 0
    ) -> list[SearchResult]:
        """Return the user's items + ideas most similar to ``query``, ordered by score."""
        vector = await self._embedding.generate(query)
        if vector is None:
            raise SemanticSearchUnavailableError("Embedding service is unavailable")

        # Fetch ``limit + offset`` from each source so the merged, sorted window is
        # large enough to satisfy the requested page across both tables.
        fetch_n = limit + offset
        item_hits = await self._item_repo.search_by_embedding(vector, user_id, limit=fetch_n)
        idea_hits = await self._idea_repo.search_by_embedding(vector, user_id, limit=fetch_n)

        results: list[SearchResult] = []
        for item, score in item_hits:
            results.append(
                SearchResult(
                    id=item.id,
                    type="item",
                    title=_make_title(item.content),
                    preview_text=_make_preview(item.description, item.content),
                    score=score,
                    created_at=item.created_at,
                )
            )
        for item, idea, score in idea_hits:
            results.append(
                SearchResult(
                    id=idea.id,
                    type="idea",
                    title=_make_title(item.content),
                    preview_text=_make_preview_for_idea(idea.tags, item.content),
                    score=score,
                    created_at=item.created_at,
                )
            )

        results.sort(key=lambda r: r.score, reverse=True)
        return results[offset : offset + limit]


def _make_title(content: str) -> str:
    """Use the first non-empty line of ``content`` as a short title."""
    for line in (content or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:_PREVIEW_CHARS]
    return (content or "").strip()[:_PREVIEW_CHARS]


def _make_preview(description: str | None, content: str) -> str:
    """Return a short preview, preferring ``description`` over raw ``content``."""
    source = description if description else content
    return (source or "").strip()[:_PREVIEW_CHARS]


def _make_preview_for_idea(tags: list[str], content: str) -> str:
    """Blend the idea's tags with the parent content for a distinctive preview."""
    tag_part = ", ".join(tags) if tags else ""
    body = (content or "").strip()
    if tag_part and body:
        return f"[{tag_part}] {body}"[:_PREVIEW_CHARS]
    if tag_part:
        return tag_part[:_PREVIEW_CHARS]
    return body[:_PREVIEW_CHARS]
