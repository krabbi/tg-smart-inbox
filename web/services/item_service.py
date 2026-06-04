"""ItemService — delete operations for the web API."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from bot.repositories.item_repository import ItemRepository


class ItemService:
    """Business logic for item mutations exposed by the web API."""

    def __init__(self, session: AsyncSession, item_repo: ItemRepository) -> None:
        self._session = session
        self._repo = item_repo

    async def delete_item(self, item_id: uuid.UUID, user_id: int) -> bool:
        """Delete the item owned by user_id; return True when deleted, False when not found."""
        deleted = await self._repo.delete_for_user(item_id, user_id)
        if deleted:
            await self._session.commit()
        return deleted

    async def bulk_delete_items(self, item_ids: list[uuid.UUID], user_id: int) -> int:
        """Delete all items in item_ids that belong to user_id; return count of deleted rows."""
        if not item_ids:
            return 0
        count = await self._repo.bulk_delete_for_user(item_ids, user_id)
        if count:
            await self._session.commit()
        return count
