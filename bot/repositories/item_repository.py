import uuid

from sqlalchemy import func, or_, select
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

    async def update_embedding(self, item_id: uuid.UUID, embedding: list[float]) -> None:
        """Persist the vector embedding on an existing Item; caller commits."""
        item = await self._session.get(Item, item_id)
        if item is None:
            return
        item.embedding = embedding
        await self._session.flush()

    async def update_scraped_text(self, item_id: uuid.UUID, scraped_text: str) -> None:
        """Persist the cached page text on an existing Item; caller commits."""
        item = await self._session.get(Item, item_id)
        if item is None:
            return
        item.scraped_text = scraped_text
        await self._session.flush()

    async def get_by_id(self, item_id: uuid.UUID) -> Item | None:
        """Return the Item with this id, or ``None`` if it does not exist."""
        return await self._session.get(Item, item_id)

    async def get_missing_embedding(self, *, limit: int = 50) -> list[Item]:
        """Return Items without a stored embedding, oldest first (batch for reindex)."""
        result = await self._session.execute(
            select(Item)
            .where(Item.embedding.is_(None))
            .order_by(Item.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_user(self, user_id: int, *, limit: int = 10) -> list[Item]:
        """Return the most recent Items for a user, newest first."""
        result = await self._session.execute(
            select(Item)
            .where(Item.user_id == user_id)
            .order_by(Item.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_recent(self, user_id: int, *, limit: int = 10, offset: int = 0) -> list[Item]:
        """Return recent Items with pagination support, newest first."""
        result = await self._session.execute(
            select(Item)
            .where(Item.user_id == user_id)
            .order_by(Item.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_by_user(self, user_id: int) -> int:
        """Return total number of Items for a user."""
        result = await self._session.execute(
            select(func.count()).select_from(Item).where(Item.user_id == user_id)
        )
        return result.scalar_one()

    async def get_recent_by_type(
        self, user_id: int, item_type: ItemType, *, limit: int = 10, offset: int = 0
    ) -> list[Item]:
        """Return recent Items of a specific type with pagination, newest first."""
        result = await self._session.execute(
            select(Item)
            .where(Item.user_id == user_id, Item.type == item_type)
            .order_by(Item.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_by_user_and_type(self, user_id: int, item_type: ItemType) -> int:
        """Return total number of Items of a specific type for a user."""
        result = await self._session.execute(
            select(func.count())
            .select_from(Item)
            .where(Item.user_id == user_id, Item.type == item_type)
        )
        return result.scalar_one()

    async def search(self, user_id: int, query: str, *, limit: int = 10) -> list[Item]:
        """Search Items by content or description, case-insensitive."""
        pattern = f"%{query.lower()}%"
        result = await self._session.execute(
            select(Item)
            .where(
                Item.user_id == user_id,
                or_(
                    func.lower(Item.content).like(pattern),
                    func.lower(Item.description).like(pattern),
                ),
            )
            .order_by(Item.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def search_by_embedding(
        self, embedding: list[float], user_id: int, *, limit: int = 20
    ) -> list[tuple[Item, float]]:
        """Return the user's Items closest to ``embedding`` as (item, score) pairs.

        Uses pgvector's cosine distance operator (``<=>``). Score is ``1 - distance``
        so higher means more similar. Items with ``embedding IS NULL`` are filtered
        out. Results are ordered by distance ascending (most similar first).
        """
        distance = Item.embedding.cosine_distance(embedding)
        result = await self._session.execute(
            select(Item, distance.label("distance"))
            .where(Item.user_id == user_id, Item.embedding.is_not(None))
            .order_by(distance.asc())
            .limit(limit)
        )
        return [(item, 1.0 - float(dist)) for item, dist in result.all()]
