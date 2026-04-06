import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.idea import Idea
from bot.models.item import Item, ItemType


class IdeaRepository:
    """CRUD access for Idea records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, item_id: uuid.UUID, tags: list[str]) -> Idea:
        """Create and flush a new Idea linked to item_id; caller commits."""
        idea = Idea(item_id=item_id, tags=tags)
        self._session.add(idea)
        await self._session.flush()
        await self._session.refresh(idea)
        return idea

    async def get_all(self, user_id: int) -> list[tuple[Item, Idea]]:
        """Return all ideas for a user as (Item, Idea) pairs, newest first."""
        result = await self._session.execute(
            select(Item, Idea)
            .join(Idea, Idea.item_id == Item.id)
            .where(Item.user_id == user_id, Item.type == ItemType.idea)
            .order_by(Item.created_at.desc())
        )
        return list(result.all())
