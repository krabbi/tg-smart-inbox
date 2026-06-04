"""Integration tests for web/routers/items.py — GET /api/items and GET /api/items/{id}."""

import uuid
from collections.abc import AsyncGenerator
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import Config
from bot.models.base import Base
from bot.models.item import Item, ItemType
from bot.repositories.item_repository import ItemRepository
from web.main import create_app

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

JWT_SECRET = "test-super-secret-key-for-items-integration"
USER_ID = 111222333
OTHER_USER_ID = 999888777


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def web_config() -> Config:
    """Minimal Config with JWT_SECRET set."""
    return Config(
        telegram_bot_token="1234567890:AAFakeTokenForTestingPurposesOnly",
        anthropic_api_key="sk-ant-fake",
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret=JWT_SECRET,
        allowed_user_ids=[],
    )


@pytest_asyncio.fixture
async def db_engine():
    """Create an in-memory SQLite engine with schema applied."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession backed by the in-memory SQLite engine."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def app_with_db(web_config: Config, db_session: AsyncSession) -> FastAPI:
    """FastAPI app with overridden DB session and fake current user."""
    from web.dependencies import get_current_user, get_db_session

    with patch("web.main.init_db"):
        test_app = create_app(web_config)

    # Override DB session to use in-memory SQLite session.
    async def override_db_session() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    # Override current user to return the test user without JWT validation.
    async def override_current_user() -> dict:
        return {"sub": str(USER_ID)}

    test_app.dependency_overrides[get_db_session] = override_db_session
    test_app.dependency_overrides[get_current_user] = override_current_user
    return test_app


@pytest_asyncio.fixture
async def seeded_app(app_with_db: FastAPI, db_session: AsyncSession) -> FastAPI:
    """App with a pre-seeded DB containing items for USER_ID and OTHER_USER_ID."""
    repo = ItemRepository(db_session)

    # Items for the authenticated user.
    await repo.create(user_id=USER_ID, type=ItemType.note, content="first note content")
    await repo.create(user_id=USER_ID, type=ItemType.task, content="buy groceries")
    await repo.create(user_id=USER_ID, type=ItemType.link, content="https://example.com")
    # Item for another user — must never appear in responses.
    await repo.create(user_id=OTHER_USER_ID, type=ItemType.note, content="other user note")
    await db_session.commit()

    return app_with_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_many(db_session: AsyncSession, user_id: int, count: int) -> list[Item]:
    """Insert `count` note items for user_id and return them."""
    repo = ItemRepository(db_session)
    items = []
    for i in range(count):
        item = await repo.create(user_id=user_id, type=ItemType.note, content=f"note {i}")
        items.append(item)
    await db_session.commit()
    return items


# ---------------------------------------------------------------------------
# GET /api/items — no auth → 401
# ---------------------------------------------------------------------------


def test_list_items_without_token_returns_401(web_config: Config) -> None:
    """GET /api/items without Authorization header returns HTTP 401."""
    with patch("web.main.init_db"):
        bare_app = create_app(web_config)
    with TestClient(bare_app, raise_server_exceptions=True) as client:
        response = client.get("/api/items")
    assert response.status_code == 401


def test_get_item_without_token_returns_401(web_config: Config) -> None:
    """GET /api/items/{id} without Authorization header returns HTTP 401."""
    with patch("web.main.init_db"):
        bare_app = create_app(web_config)
    with TestClient(bare_app, raise_server_exceptions=True) as client:
        response = client.get(f"/api/items/{uuid.uuid4()}")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/items — basic list
# ---------------------------------------------------------------------------


def test_list_items_returns_200_with_correct_structure(seeded_app: FastAPI) -> None:
    """GET /api/items returns HTTP 200 with items/page/total_pages structure."""
    with TestClient(seeded_app, raise_server_exceptions=True) as client:
        response = client.get("/api/items")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    assert "page" in body
    assert "total_pages" in body
    assert body["page"] == 1


def test_list_items_scoped_to_authenticated_user(seeded_app: FastAPI) -> None:
    """GET /api/items only returns items belonging to the authenticated user."""
    with TestClient(seeded_app, raise_server_exceptions=True) as client:
        response = client.get("/api/items")
    assert response.status_code == 200
    items = response.json()["items"]
    # Seeded 3 items for USER_ID and 1 for OTHER_USER_ID.
    assert len(items) == 3
    for item in items:
        # All returned items must have the expected shape.
        assert "id" in item
        assert "type" in item
        assert "preview" in item
        assert "created_at" in item


def test_list_items_each_has_expected_fields(seeded_app: FastAPI) -> None:
    """Each item in the list has id, type, title, preview, created_at fields."""
    with TestClient(seeded_app, raise_server_exceptions=True) as client:
        response = client.get("/api/items")
    items = response.json()["items"]
    assert len(items) > 0
    for item in items:
        assert set(item.keys()) == {"id", "type", "title", "preview", "created_at"}


# ---------------------------------------------------------------------------
# GET /api/items?type=... — type filter
# ---------------------------------------------------------------------------


def test_list_items_filter_by_type_task(seeded_app: FastAPI) -> None:
    """?type=task returns only task items for the authenticated user."""
    with TestClient(seeded_app, raise_server_exceptions=True) as client:
        response = client.get("/api/items", params={"type": "task"})
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["type"] == "task"
    assert "groceries" in items[0]["preview"]


def test_list_items_filter_by_type_note(seeded_app: FastAPI) -> None:
    """?type=note returns only note items for the authenticated user."""
    with TestClient(seeded_app, raise_server_exceptions=True) as client:
        response = client.get("/api/items", params={"type": "note"})
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["type"] == "note"


def test_list_items_filter_by_type_link(seeded_app: FastAPI) -> None:
    """?type=link returns only link items for the authenticated user."""
    with TestClient(seeded_app, raise_server_exceptions=True) as client:
        response = client.get("/api/items", params={"type": "link"})
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["type"] == "link"


def test_list_items_filter_by_type_returns_empty_when_no_match(seeded_app: FastAPI) -> None:
    """?type=idea returns empty list when user has no idea items."""
    with TestClient(seeded_app, raise_server_exceptions=True) as client:
        response = client.get("/api/items", params={"type": "idea"})
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_list_items_invalid_type_returns_400(seeded_app: FastAPI) -> None:
    """?type=invalid returns HTTP 400."""
    with TestClient(seeded_app, raise_server_exceptions=True) as client:
        response = client.get("/api/items", params={"type": "invalid"})
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/items?q=... — full-text search
# ---------------------------------------------------------------------------


def test_list_items_search_returns_matching_items(seeded_app: FastAPI) -> None:
    """?q=groceries returns items whose content matches the query."""
    with TestClient(seeded_app, raise_server_exceptions=True) as client:
        response = client.get("/api/items", params={"q": "groceries"})
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert "groceries" in items[0]["preview"]


def test_list_items_search_is_case_insensitive(seeded_app: FastAPI) -> None:
    """?q=GROCERIES (upper-case) matches the same item as lower-case query."""
    with TestClient(seeded_app, raise_server_exceptions=True) as client:
        response = client.get("/api/items", params={"q": "GROCERIES"})
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1


def test_list_items_search_returns_empty_for_no_match(seeded_app: FastAPI) -> None:
    """?q=nonexistent returns an empty items list."""
    with TestClient(seeded_app, raise_server_exceptions=True) as client:
        response = client.get("/api/items", params={"q": "xyznonexistent"})
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_list_items_search_scoped_to_user(seeded_app: FastAPI) -> None:
    """?q searches only the authenticated user's items, not other users'."""
    with TestClient(seeded_app, raise_server_exceptions=True) as client:
        response = client.get("/api/items", params={"q": "other user"})
    assert response.status_code == 200
    # "other user note" belongs to OTHER_USER_ID — must not appear.
    assert response.json()["items"] == []


# ---------------------------------------------------------------------------
# GET /api/items — pagination
# ---------------------------------------------------------------------------


async def test_list_items_pagination_total_pages_calculated_correctly(
    app_with_db: FastAPI, db_session: AsyncSession
) -> None:
    """total_pages is ceil(total / PAGE_SIZE); with 21 items and PAGE_SIZE=20 → 2 pages."""
    await _seed_many(db_session, USER_ID, 21)

    with TestClient(app_with_db, raise_server_exceptions=True) as client:
        response = client.get("/api/items")
    assert response.status_code == 200
    body = response.json()
    assert body["total_pages"] == 2
    assert len(body["items"]) == 20


async def test_list_items_page_2_returns_remaining_items(
    app_with_db: FastAPI, db_session: AsyncSession
) -> None:
    """Page 2 returns the remaining items when total > PAGE_SIZE."""
    await _seed_many(db_session, USER_ID, 21)

    with TestClient(app_with_db, raise_server_exceptions=True) as client:
        response = client.get("/api/items", params={"page": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 2
    assert len(body["items"]) == 1


def test_list_items_empty_db_returns_one_total_page(app_with_db: FastAPI) -> None:
    """GET /api/items on empty DB returns page=1, total_pages=1, items=[]."""
    with TestClient(app_with_db, raise_server_exceptions=True) as client:
        response = client.get("/api/items")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["page"] == 1
    assert body["total_pages"] == 1


# ---------------------------------------------------------------------------
# GET /api/items/{id} — detail
# ---------------------------------------------------------------------------


async def test_get_item_returns_200_with_full_detail(
    seeded_app: FastAPI, db_session: AsyncSession
) -> None:
    """GET /api/items/{id} returns HTTP 200 with full item detail for own item."""
    items = await _seed_many(db_session, USER_ID, 1)
    item_id = str(items[0].id)

    with TestClient(seeded_app, raise_server_exceptions=True) as client:
        response = client.get(f"/api/items/{item_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == item_id
    assert set(body.keys()) == {
        "id",
        "type",
        "content",
        "title",
        "description",
        "scraped_text",
        "created_at",
    }


def test_get_item_returns_404_for_unknown_id(seeded_app: FastAPI) -> None:
    """GET /api/items/{id} returns HTTP 404 for a non-existent item ID."""
    with TestClient(seeded_app, raise_server_exceptions=True) as client:
        response = client.get(f"/api/items/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_get_item_returns_404_for_other_users_item(
    app_with_db: FastAPI, db_session: AsyncSession
) -> None:
    """GET /api/items/{id} returns HTTP 404 for an item belonging to another user."""
    repo = ItemRepository(db_session)
    item = await repo.create(user_id=OTHER_USER_ID, type=ItemType.note, content="secret note")
    await db_session.commit()
    other_item_id = str(item.id)

    with TestClient(app_with_db, raise_server_exceptions=True) as client:
        response = client.get(f"/api/items/{other_item_id}")
    assert response.status_code == 404


def test_get_item_returns_400_for_invalid_uuid(seeded_app: FastAPI) -> None:
    """GET /api/items/{id} returns HTTP 400 when id is not a valid UUID."""
    with TestClient(seeded_app, raise_server_exceptions=True) as client:
        response = client.get("/api/items/not-a-uuid")
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Router registration
# ---------------------------------------------------------------------------


def test_create_app_registers_items_list_route(web_config: Config) -> None:
    """The /api/items route is registered on the app."""
    with patch("web.main.init_db"):
        test_app = create_app(web_config)
    routes = {route.path for route in test_app.routes}  # type: ignore[attr-defined]
    assert "/api/items" in routes


def test_create_app_registers_items_detail_route(web_config: Config) -> None:
    """The /api/items/{item_id} route is registered on the app."""
    with patch("web.main.init_db"):
        test_app = create_app(web_config)
    routes = {route.path for route in test_app.routes}  # type: ignore[attr-defined]
    assert "/api/items/{item_id}" in routes


# ---------------------------------------------------------------------------
# DELETE /api/items/{id} — single delete
# ---------------------------------------------------------------------------


def test_delete_item_without_token_returns_401(web_config: Config) -> None:
    """DELETE /api/items/{id} without Authorization header returns HTTP 401."""
    with patch("web.main.init_db"):
        bare_app = create_app(web_config)
    with TestClient(bare_app, raise_server_exceptions=True) as client:
        response = client.delete(f"/api/items/{uuid.uuid4()}")
    assert response.status_code == 401


async def test_delete_item_returns_204_and_item_is_gone(
    app_with_db: FastAPI, db_session: AsyncSession
) -> None:
    """DELETE /api/items/{id} for own item returns HTTP 204 and item is no longer retrievable."""
    repo = ItemRepository(db_session)
    item = await repo.create(user_id=USER_ID, type=ItemType.note, content="to be deleted")
    await db_session.commit()
    item_id = str(item.id)

    with TestClient(app_with_db, raise_server_exceptions=True) as client:
        response = client.delete(f"/api/items/{item_id}")
    assert response.status_code == 204
    assert response.content == b""

    # Item must no longer exist in DB.
    gone = await repo.get_by_id_for_user(uuid.UUID(item_id), USER_ID)
    assert gone is None


async def test_delete_item_returns_404_for_other_users_item(
    app_with_db: FastAPI, db_session: AsyncSession
) -> None:
    """DELETE /api/items/{id} for another user's item returns HTTP 404 without deleting it."""
    repo = ItemRepository(db_session)
    item = await repo.create(user_id=OTHER_USER_ID, type=ItemType.note, content="other secret")
    await db_session.commit()

    with TestClient(app_with_db, raise_server_exceptions=True) as client:
        response = client.delete(f"/api/items/{item.id}")
    assert response.status_code == 404

    # Item must still exist for its real owner.
    still_there = await repo.get_by_id_for_user(item.id, OTHER_USER_ID)
    assert still_there is not None


def test_delete_item_returns_404_for_unknown_id(app_with_db: FastAPI) -> None:
    """DELETE /api/items/{id} for a non-existent id returns HTTP 404."""
    with TestClient(app_with_db, raise_server_exceptions=True) as client:
        response = client.delete(f"/api/items/{uuid.uuid4()}")
    assert response.status_code == 404


def test_delete_item_returns_400_for_invalid_uuid(app_with_db: FastAPI) -> None:
    """DELETE /api/items/{id} returns HTTP 400 when id is not a valid UUID."""
    with TestClient(app_with_db, raise_server_exceptions=True) as client:
        response = client.delete("/api/items/not-a-valid-uuid")
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# DELETE /api/items — bulk delete
# ---------------------------------------------------------------------------


def test_bulk_delete_without_token_returns_401(web_config: Config) -> None:
    """DELETE /api/items without Authorization header returns HTTP 401."""
    with patch("web.main.init_db"):
        bare_app = create_app(web_config)
    with TestClient(bare_app, raise_server_exceptions=True) as client:
        response = client.request("DELETE", "/api/items", json={"ids": []})
    assert response.status_code == 401


def test_bulk_delete_empty_ids_returns_zero(app_with_db: FastAPI) -> None:
    """DELETE /api/items with empty ids list returns {"deleted": 0} without error."""
    with TestClient(app_with_db, raise_server_exceptions=True) as client:
        response = client.request("DELETE", "/api/items", json={"ids": []})
    assert response.status_code == 200
    assert response.json() == {"deleted": 0}


async def test_bulk_delete_own_items_returns_correct_count(
    app_with_db: FastAPI, db_session: AsyncSession
) -> None:
    """DELETE /api/items deletes all own ids and returns the correct deleted count."""
    items = await _seed_many(db_session, USER_ID, 3)
    ids = [str(item.id) for item in items]

    with TestClient(app_with_db, raise_server_exceptions=True) as client:
        response = client.request("DELETE", "/api/items", json={"ids": ids})
    assert response.status_code == 200
    assert response.json() == {"deleted": 3}

    # All three items must be gone.
    repo = ItemRepository(db_session)
    for item in items:
        assert await repo.get_by_id_for_user(item.id, USER_ID) is None


async def test_bulk_delete_mixed_ids_ignores_foreign_and_missing(
    app_with_db: FastAPI, db_session: AsyncSession
) -> None:
    """Bulk delete with own, foreign, and non-existent ids returns only own-item count."""
    repo = ItemRepository(db_session)
    own_item = await repo.create(user_id=USER_ID, type=ItemType.note, content="mine")
    other_item = await repo.create(user_id=OTHER_USER_ID, type=ItemType.note, content="not mine")
    await db_session.commit()

    ids = [
        str(own_item.id),
        str(other_item.id),  # foreign — must be silently ignored
        str(uuid.uuid4()),  # non-existent — must be silently ignored
    ]

    with TestClient(app_with_db, raise_server_exceptions=True) as client:
        response = client.request("DELETE", "/api/items", json={"ids": ids})
    assert response.status_code == 200
    assert response.json() == {"deleted": 1}

    # Own item deleted; other user's item untouched.
    assert await repo.get_by_id_for_user(own_item.id, USER_ID) is None
    assert await repo.get_by_id_for_user(other_item.id, OTHER_USER_ID) is not None


async def test_bulk_delete_all_foreign_ids_returns_zero(
    app_with_db: FastAPI, db_session: AsyncSession
) -> None:
    """Bulk delete where every id belongs to another user returns {"deleted": 0}."""
    repo = ItemRepository(db_session)
    item = await repo.create(user_id=OTHER_USER_ID, type=ItemType.note, content="not mine")
    await db_session.commit()

    with TestClient(app_with_db, raise_server_exceptions=True) as client:
        response = client.request("DELETE", "/api/items", json={"ids": [str(item.id)]})
    assert response.status_code == 200
    assert response.json() == {"deleted": 0}


async def test_bulk_delete_duplicate_ids_counted_once(
    app_with_db: FastAPI, db_session: AsyncSession
) -> None:
    """Bulk delete with duplicate ids for the same item counts it only once."""
    repo = ItemRepository(db_session)
    item = await repo.create(user_id=USER_ID, type=ItemType.note, content="unique")
    await db_session.commit()
    dup_id = str(item.id)

    with TestClient(app_with_db, raise_server_exceptions=True) as client:
        response = client.request("DELETE", "/api/items", json={"ids": [dup_id, dup_id, dup_id]})
    assert response.status_code == 200
    assert response.json() == {"deleted": 1}
