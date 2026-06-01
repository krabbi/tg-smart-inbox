import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.item import Item, ItemType
from bot.repositories.item_repository import ItemRepository
from bot.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SavedTask:
    """Result of saving a task — the persisted Item plus indexing status."""

    item: Item
    indexed: bool = False


class TaskService:
    """Save task items to the database and attempt semantic indexing."""

    def __init__(
        self,
        session: AsyncSession,
        item_repo: ItemRepository,
        embedding_service: EmbeddingService | None = None,
    ) -> None:
        self._session = session
        self._repo = item_repo
        self._embedding = embedding_service

    async def save(self, text: str, user_id: int) -> SavedTask:
        """Persist a task Item and attempt to index it; return SavedTask with indexing status.

        The save itself always succeeds. Embedding is best-effort: when the
        Voyage AI key is missing or the call fails, the task is still persisted
        and ``indexed`` is set to ``False`` so the handler can surface a notice
        with a retry button.
        """
        item = await self._repo.create(user_id=user_id, type=ItemType.task, content=text)
        await self._session.commit()

        indexed = await self._try_index(item)
        return SavedTask(item=item, indexed=indexed)

    async def _try_index(self, item: Item) -> bool:
        """Generate and store the item's embedding; return True on success, False otherwise."""
        if self._embedding is None:
            return False
        try:
            vector = await self._embedding.generate_for_item(item)
        except Exception:
            logger.exception("Embedding generation raised for task item %s", item.id)
            return False
        if vector is None:
            return False
        try:
            await self._repo.update_embedding(item.id, vector)
            await self._session.commit()
        except Exception:
            logger.exception("Failed to persist embedding for task item %s", item.id)
            await self._session.rollback()
            return False
        return True
