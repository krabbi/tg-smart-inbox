from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.item import Item, ItemType
from bot.repositories.item_repository import ItemRepository


@dataclass(frozen=True)
class SavedNote:
    """Result of saving a note."""

    item: Item


class NoteService:
    """Save note items to the database."""

    def __init__(self, session: AsyncSession, item_repo: ItemRepository) -> None:
        self._session = session
        self._repo = item_repo

    async def save(self, text: str, user_id: int) -> SavedNote:
        """Persist a note Item and return SavedNote."""
        item = await self._repo.create(user_id=user_id, type=ItemType.note, content=text)
        await self._session.commit()
        return SavedNote(item=item)
