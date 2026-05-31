import asyncio
import enum
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.idea import Idea
from bot.models.item import Item
from bot.repositories.idea_repository import IdeaRepository
from bot.repositories.item_repository import ItemRepository
from bot.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)

# Hard cap on records processed per ``reindex_all_for_user`` invocation. Keeps a
# single user from monopolising the Voyage AI rate budget; remaining records get
# picked up on subsequent runs.
_DEFAULT_MAX_ITEMS = 200

# Pause between successive Voyage AI calls during a bulk reindex. Mirrors the
# scheduler's throttle to stay below the provider's ~3 req/s ceiling.
_THROTTLE_SECONDS = 0.1


class ReindexResult(enum.Enum):
    """Outcome of a single-record reindex attempt."""

    SUCCESS = "success"
    ALREADY_INDEXED = "already_indexed"
    NOT_FOUND = "not_found"
    SERVICE_UNAVAILABLE = "service_unavailable"


@dataclass(frozen=True)
class ReindexSummary:
    """Aggregate outcome of a bulk reindex run for one user."""

    succeeded: int
    failed: int
    total_found: int
    truncated: bool


class ReindexService:
    """Regenerate missing embeddings for one user's Items and Ideas."""

    def __init__(
        self,
        embedding_service: EmbeddingService,
        item_repository: ItemRepository,
        idea_repository: IdeaRepository,
        session: AsyncSession,
    ) -> None:
        self._embedding = embedding_service
        self._items = item_repository
        self._ideas = idea_repository
        self._session = session

    async def count_unindexed_for_user(self, user_id: int) -> int:
        """Return total Items + Ideas without an embedding for one user.

        Used by the ``/reindex`` handler to short-circuit when the backlog is
        empty and to decide whether the pre-run "Found N records" message needs
        the "(first 200 will be processed)" suffix.
        """
        items = await self._items.count_without_embedding(user_id)
        ideas = await self._ideas.count_without_embedding(user_id)
        return items + ideas

    async def reindex_item(self, item_id: uuid.UUID, user_id: int) -> ReindexResult:
        """Generate and persist an embedding for a single Item; return the outcome."""
        item = await self._items.get_by_id_for_user(item_id, user_id)
        if item is None:
            return ReindexResult.NOT_FOUND
        if item.embedding is not None:
            return ReindexResult.ALREADY_INDEXED

        text = self._build_item_text(item)
        vector = await self._embedding.generate(text)
        if vector is None:
            return ReindexResult.SERVICE_UNAVAILABLE

        await self._items.update_embedding(item.id, vector)
        await self._session.commit()
        return ReindexResult.SUCCESS

    async def reindex_idea(self, idea_id: uuid.UUID, user_id: int) -> ReindexResult:
        """Generate and persist an embedding for a single Idea; return the outcome."""
        idea = await self._ideas.get_by_id_for_user(idea_id, user_id)
        if idea is None:
            return ReindexResult.NOT_FOUND
        if idea.embedding is not None:
            return ReindexResult.ALREADY_INDEXED

        text = self._build_idea_text(idea)
        vector = await self._embedding.generate(text)
        if vector is None:
            return ReindexResult.SERVICE_UNAVAILABLE

        await self._ideas.update_embedding(idea.id, vector)
        await self._session.commit()
        return ReindexResult.SUCCESS

    async def reindex_all_for_user(
        self, user_id: int, max_items: int = _DEFAULT_MAX_ITEMS
    ) -> ReindexSummary:
        """Reindex up to ``max_items`` of one user's unindexed Items and Ideas in one pass.

        Items are processed before Ideas. The combined limit is enforced across both
        sources: once the budget is exhausted, ``truncated`` is set to ``True`` and
        the rest of the backlog stays for the next run. A 100 ms pause is inserted
        between Voyage AI calls to stay under the provider's rate limit.

        If the very first call to ``EmbeddingService.generate`` returns ``None``, the
        run is aborted immediately — the Voyage AI endpoint is assumed unreachable
        for the entire pass — and the result reflects "nothing succeeded" over the
        backlog window that was already loaded.
        """
        items = await self._items.list_without_embedding(user_id, limit=max_items)
        remaining = max_items - len(items)
        idea_rows: list[tuple[Item, Idea]] = []
        if remaining > 0:
            idea_rows = await self._ideas.list_without_embedding(user_id, limit=remaining)

        total_found = len(items) + len(idea_rows)
        truncated = await self._is_truncated(
            user_id, loaded_items=len(items), loaded_ideas=len(idea_rows), max_items=max_items
        )

        if total_found == 0:
            return ReindexSummary(succeeded=0, failed=0, total_found=0, truncated=truncated)

        succeeded = 0
        failed = 0
        first_call = True

        for item in items:
            if not first_call:
                await asyncio.sleep(_THROTTLE_SECONDS)
            text = self._build_item_text(item)
            vector = await self._embedding.generate(text)
            if vector is None:
                if first_call:
                    # Voyage AI is down for this pass — bail out and report the
                    # whole backlog as failed for this run.
                    return ReindexSummary(
                        succeeded=0,
                        failed=total_found,
                        total_found=total_found,
                        truncated=truncated,
                    )
                failed += 1
                first_call = False
                continue
            await self._items.update_embedding(item.id, vector)
            await self._session.commit()
            succeeded += 1
            first_call = False

        for item, idea in idea_rows:
            if not first_call:
                await asyncio.sleep(_THROTTLE_SECONDS)
            # Attach the parent Item in memory so ``_build_idea_text`` can read
            # ``content`` without an extra DB round-trip — the loaded row pair is
            # the canonical (Item, Idea) tuple from ``list_without_embedding``.
            idea.item = item
            text = self._build_idea_text(idea)
            vector = await self._embedding.generate(text)
            if vector is None:
                if first_call:
                    return ReindexSummary(
                        succeeded=0,
                        failed=total_found,
                        total_found=total_found,
                        truncated=truncated,
                    )
                failed += 1
                first_call = False
                continue
            await self._ideas.update_embedding(idea.id, vector)
            await self._session.commit()
            succeeded += 1
            first_call = False

        return ReindexSummary(
            succeeded=succeeded,
            failed=failed,
            total_found=total_found,
            truncated=truncated,
        )

    async def _is_truncated(
        self, user_id: int, *, loaded_items: int, loaded_ideas: int, max_items: int
    ) -> bool:
        """Return True when the loaded window does not cover the user's full backlog."""
        if loaded_items + loaded_ideas < max_items:
            # The combined fetch didn't hit the budget, so by construction it
            # returned every unindexed row available.
            return False
        total = await self._items.count_without_embedding(user_id)
        total += await self._ideas.count_without_embedding(user_id)
        return total > loaded_items + loaded_ideas

    @staticmethod
    def _build_item_text(item: Item) -> str:
        """Concatenate the Item's searchable fields (content, description, scraped_text).

        Mirrors what ``LinkService``/``TaskService``/``NoteService`` feed into the
        embedding pipeline at first save: every non-empty field is joined with a
        blank-line separator so paragraph boundaries survive in the embedding input.
        """
        parts: list[str] = []
        if item.content:
            parts.append(item.content)
        if item.description:
            parts.append(item.description)
        if item.scraped_text:
            parts.append(item.scraped_text)
        return "\n\n".join(parts).strip()

    @staticmethod
    def _build_idea_text(idea: Idea) -> str:
        """Blend the parent Item's content with the Idea's tags for idea-level search.

        Mirrors ``IdeaService``'s initial save path: the parent ``content`` carries
        the actual idea text, the tags surface as a ``Теги: ...`` line so they
        contribute to similarity scoring without dominating the vector.
        """
        parts: list[str] = []
        item = getattr(idea, "item", None)
        if item is not None and getattr(item, "content", None):
            parts.append(item.content)
        if idea.tags:
            parts.append("Теги: " + ", ".join(idea.tags))
        return "\n\n".join(parts).strip()
