from dataclasses import dataclass

from bot.models.item import Item
from bot.repositories.item_repository import ItemRepository

_SEARCH_LIMIT = 10
_PAGE_SIZE = 10


@dataclass(frozen=True)
class ListPage:
    """A page of items with pagination metadata."""

    items: list[Item]
    page: int
    total: int

    @property
    def has_prev(self) -> bool:
        """True if there is a previous page."""
        return self.page > 0

    @property
    def has_next(self) -> bool:
        """True if there are more pages after this one."""
        return (self.page + 1) * _PAGE_SIZE < self.total


class ListService:
    """Read-only queries for /list and /search commands."""

    def __init__(self, item_repo: ItemRepository) -> None:
        self._repo = item_repo

    async def list_recent(self, user_id: int, page: int = 0) -> ListPage:
        """Return a page of recent items with total count for pagination."""
        total = await self._repo.count_by_user(user_id)
        items = await self._repo.get_recent(user_id, limit=_PAGE_SIZE, offset=page * _PAGE_SIZE)
        return ListPage(items=items, page=page, total=total)

    async def search(self, user_id: int, query: str) -> list[Item]:
        """Return up to 10 items matching query in content or description."""
        return await self._repo.search(user_id, query, limit=_SEARCH_LIMIT)
