"""Items router — GET /api/items and GET /api/items/{id}."""

import math
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.item import Item, ItemType
from bot.repositories.item_repository import ItemRepository
from web.dependencies import get_current_user, get_db_session

router = APIRouter(prefix="/api/items", tags=["items"])

# Number of items returned per page.
PAGE_SIZE = 20


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ItemSummary(BaseModel):
    """Compact item representation used in list responses."""

    id: str
    type: str
    title: str | None
    preview: str
    created_at: str


class ItemDetail(BaseModel):
    """Full item representation returned by the detail endpoint."""

    id: str
    type: str
    content: str
    title: str | None
    description: str | None
    scraped_text: str | None
    created_at: str


class ItemListResponse(BaseModel):
    """Paginated list of items."""

    items: list[ItemSummary]
    page: int
    total_pages: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ITEM_TYPE_MAP: dict[str, ItemType] = {
    "task": ItemType.task,
    "note": ItemType.note,
    "link": ItemType.link,
    "idea": ItemType.idea,
    "media": ItemType.media,
}


def _item_to_summary(item: Item) -> ItemSummary:
    """Convert an Item ORM object to an ItemSummary schema."""
    # Build a short preview: prefer description, fall back to first 120 chars of content.
    preview = item.description if item.description else item.content[:120]

    return ItemSummary(
        id=str(item.id),
        type=item.type.value,
        title=item.title,
        preview=preview,
        created_at=item.created_at.isoformat(),
    )


def _item_to_detail(item: Item) -> ItemDetail:
    """Convert an Item ORM object to an ItemDetail schema."""
    return ItemDetail(
        id=str(item.id),
        type=item.type.value,
        content=item.content,
        title=item.title,
        description=item.description,
        scraped_text=item.scraped_text,
        created_at=item.created_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=ItemListResponse)
async def list_items(
    current_user: Annotated[dict, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    type: str | None = None,
    page: int = 1,
    q: str | None = None,
) -> ItemListResponse:
    """Return a paginated list of items for the authenticated user.

    Supports optional type filter and full-text search via `q`.
    Returns HTTP 400 when `type` is not a recognised ItemType value.
    """
    if page < 1:
        page = 1

    user_id = int(current_user["sub"])
    repo = ItemRepository(session)
    offset = (page - 1) * PAGE_SIZE

    # Validate the optional type filter.
    item_type: ItemType | None = None
    if type is not None:
        item_type = _ITEM_TYPE_MAP.get(type.lower())
        if item_type is None:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid type '{type}'. Must be one of: {', '.join(_ITEM_TYPE_MAP)}",
            )

    if q:
        items = await repo.search(user_id, q, limit=PAGE_SIZE, offset=offset)
        total = await repo.count_search(user_id, q)
    elif item_type is not None:
        items = await repo.get_recent_by_type(user_id, item_type, limit=PAGE_SIZE, offset=offset)
        total = await repo.count_by_user_and_type(user_id, item_type)
    else:
        items = await repo.get_recent(user_id, limit=PAGE_SIZE, offset=offset)
        total = await repo.count_by_user(user_id)

    total_pages = max(1, math.ceil(total / PAGE_SIZE))

    return ItemListResponse(
        items=[_item_to_summary(item) for item in items],
        page=page,
        total_pages=total_pages,
    )


@router.get("/{item_id}", response_model=ItemDetail)
async def get_item(
    item_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ItemDetail:
    """Return full detail for a single item owned by the authenticated user.

    Returns HTTP 404 when the item does not exist or belongs to a different user.
    Returns HTTP 400 when item_id is not a valid UUID.
    """
    try:
        parsed_id = uuid.UUID(item_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid item id") from exc

    user_id = int(current_user["sub"])
    repo = ItemRepository(session)
    item = await repo.get_by_id_for_user(parsed_id, user_id)

    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    return _item_to_detail(item)
