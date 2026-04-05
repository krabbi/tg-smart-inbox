from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.item import Item, ItemType


class ItemRepository:
    """CRUD access for Item records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, user_id: int, type: ItemType, content: str) -> Item:
        """Create and flush a new Item; caller is responsible for commit."""
        item = Item(user_id=user_id, type=type, content=content)
        self._session.add(item)
        await self._session.flush()
        await self._session.refresh(item)
        return item

    async def get_by_user(self, user_id: int, *, limit: int = 10) -> list[Item]:
        """Return the most recent Items for a user, newest first."""
        result = await self._session.execute(
            select(Item)
            .where(Item.user_id == user_id)
            .order_by(Item.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
