import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import bot.db as db_module
from bot.db import create_tables, get_session, get_session_factory, init_db
from bot.models.item import Item, ItemType

TEST_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(autouse=True)
def reset_db_state():
    """Reset global _session_factory between tests."""
    original = db_module._session_factory
    yield
    db_module._session_factory = original


async def test_init_db_sets_session_factory() -> None:
    init_db(TEST_URL)
    factory = get_session_factory()
    assert factory is not None


def test_get_session_factory_raises_before_init() -> None:
    db_module._session_factory = None
    with pytest.raises(RuntimeError, match="Database not initialized"):
        get_session_factory()


async def test_get_session_yields_async_session() -> None:
    init_db(TEST_URL)
    await create_tables(TEST_URL)
    async with get_session() as session:
        assert isinstance(session, AsyncSession)


async def test_create_tables_does_not_raise() -> None:
    # Verifies create_tables runs without errors (schema creation smoke test)
    await create_tables(TEST_URL)


async def test_get_session_can_write_and_read(db_session: AsyncSession) -> None:
    # Verifies a session obtained via the fixture supports read/write operations
    item = Item(user_id=1, type=ItemType.note, content="hello")
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    assert item.id is not None
