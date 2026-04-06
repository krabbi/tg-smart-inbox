from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.item import Item, ItemType
from bot.repositories.item_repository import ItemRepository


@dataclass(frozen=True)
class SavedTask:
    """Result of saving a task."""

    item: Item


class TaskService:
    """Save task items to the database."""

    def __init__(self, session: AsyncSession, item_repo: ItemRepository) -> None:
        self._session = session
        self._repo = item_repo

    async def save(self, text: str, user_id: int) -> SavedTask:
        """Persist a task Item and return SavedTask."""
        item = await self._repo.create(user_id=user_id, type=ItemType.task, content=text)
        await self._session.commit()
        return SavedTask(item=item)
