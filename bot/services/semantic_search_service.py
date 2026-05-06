import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from bot.exceptions import SemanticSearchUnavailableError
from bot.models.item import Item, ItemType
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
    # Underlying Item type (``link``/``note``/``task``/``media``/``idea``) — lets
    # the renderer decide whether to append a URL/Drive-link in parentheses after
    # the title. Always equals ``"idea"`` for hits that came from the ideas table.
    item_type: str = "note"
    # Original URL/Drive link when ``item_type`` is ``link`` or ``media``; the
    # renderer prints it as ``{title} ({url})``. ``None`` for everything else.
    url: str | None = None


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
                    title=_make_title_for_item(item),
                    preview_text=_make_preview_for_item(item),
                    score=score,
                    created_at=item.created_at,
                    item_type=item.type.value,
                    # Both link and media items keep their original URL/Drive link
                    # in ``content`` — surface it so the formatter can render
                    # ``{title} ({url})``. Other types have no URL.
                    url=item.content if item.type in {ItemType.link, ItemType.media} else None,
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
                    item_type=ItemType.idea.value,
                    url=None,
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


def _make_title_for_item(item: Item) -> str:
    """Pick the best display title: stored Item.title for links/media, else first line."""
    # Links carry a scraped page title; media items carry a Vision-generated
    # description in ``Item.description``. Both should win over the raw URL.
    if item.type == ItemType.link and getattr(item, "title", None):
        return _make_title(item.title or "")
    if item.type == ItemType.media and item.description:
        return _make_title(item.description)
    return _make_title(item.content)


def _make_preview_for_item(item: Item) -> str:
    """Build the secondary preview line for a non-idea item.

    For links the preview is the start of ``scraped_text`` so the user can tell
    what the article is actually about; without scraped text we leave the
    preview blank (the renderer hides the line when both halves are blank or
    duplicate the title). For other types we keep the legacy
    description-then-content fallback.
    """
    if item.type == ItemType.link:
        if item.scraped_text:
            return item.scraped_text.strip()[:_PREVIEW_CHARS]
        return ""
    return _make_preview(item.description, item.content)


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
