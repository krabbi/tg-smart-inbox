import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.idea import Idea
from bot.models.item import EMBEDDING_DIM, Item, ItemType
from bot.models.reminder import Reminder


async def test_create_item(db_session: AsyncSession) -> None:
    item = Item(
        user_id=123456789,
        type=ItemType.note,
        content="Test note content",
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)

    assert item.id is not None
    assert isinstance(item.id, uuid.UUID)
    assert item.user_id == 123456789
    assert item.type == ItemType.note
    assert item.content == "Test note content"
    assert item.description is None


async def test_item_with_description(db_session: AsyncSession) -> None:
    item = Item(
        user_id=111,
        type=ItemType.link,
        content="https://example.com",
        description="AI-generated summary",
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)

    assert item.description == "AI-generated summary"


async def test_all_item_types(db_session: AsyncSession) -> None:
    for item_type in ItemType:
        item = Item(user_id=1, type=item_type, content=f"content for {item_type.value}")
        db_session.add(item)
    await db_session.commit()

    result = await db_session.execute(select(Item))
    items = result.scalars().all()
    assert len(items) == len(ItemType)


async def test_create_reminder(db_session: AsyncSession) -> None:
    item = Item(user_id=1, type=ItemType.task, content="Buy milk")
    db_session.add(item)
    await db_session.flush()

    remind_at = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    reminder = Reminder(item_id=item.id, remind_at=remind_at)
    db_session.add(reminder)
    await db_session.commit()
    await db_session.refresh(reminder)

    assert reminder.id is not None
    assert reminder.item_id == item.id
    assert reminder.is_sent is False
    assert reminder.is_cancelled is False


async def test_update_reminder_sent(db_session: AsyncSession) -> None:
    item = Item(user_id=1, type=ItemType.task, content="Call mom")
    db_session.add(item)
    await db_session.flush()

    reminder = Reminder(
        item_id=item.id,
        remind_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    db_session.add(reminder)
    await db_session.commit()

    reminder.is_sent = True
    await db_session.commit()
    await db_session.refresh(reminder)

    assert reminder.is_sent is True


async def test_create_idea(db_session: AsyncSession) -> None:
    item = Item(user_id=1, type=ItemType.idea, content="Build a rocket")
    db_session.add(item)
    await db_session.flush()

    idea = Idea(item_id=item.id, tags=["space", "engineering"])
    db_session.add(idea)
    await db_session.commit()
    await db_session.refresh(idea)

    assert idea.id is not None
    assert idea.item_id == item.id
    assert idea.tags == ["space", "engineering"]


async def test_idea_default_empty_tags(db_session: AsyncSession) -> None:
    item = Item(user_id=1, type=ItemType.idea, content="Some idea")
    db_session.add(item)
    await db_session.flush()

    idea = Idea(item_id=item.id)
    db_session.add(idea)
    await db_session.commit()
    await db_session.refresh(idea)

    assert idea.tags == []


async def test_item_cascade_delete_reminder(db_session: AsyncSession) -> None:
    item = Item(user_id=1, type=ItemType.task, content="Task to delete")
    db_session.add(item)
    await db_session.flush()

    reminder = Reminder(
        item_id=item.id,
        remind_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    db_session.add(reminder)
    await db_session.commit()

    reminder_id = reminder.id
    await db_session.delete(item)
    await db_session.commit()

    result = await db_session.execute(select(Reminder).where(Reminder.id == reminder_id))
    assert result.scalar_one_or_none() is None


async def test_item_cascade_delete_idea(db_session: AsyncSession) -> None:
    item = Item(user_id=1, type=ItemType.idea, content="Idea to delete")
    db_session.add(item)
    await db_session.flush()

    idea = Idea(item_id=item.id, tags=["test"])
    db_session.add(idea)
    await db_session.commit()

    idea_id = idea.id
    await db_session.delete(item)
    await db_session.commit()

    result = await db_session.execute(select(Idea).where(Idea.id == idea_id))
    assert result.scalar_one_or_none() is None


async def test_query_items_by_user(db_session: AsyncSession) -> None:
    for i in range(3):
        db_session.add(Item(user_id=111, type=ItemType.note, content=f"note {i}"))
    db_session.add(Item(user_id=999, type=ItemType.note, content="other user"))
    await db_session.commit()

    result = await db_session.execute(select(Item).where(Item.user_id == 111))
    items = result.scalars().all()
    assert len(items) == 3


async def test_item_embedding_and_scraped_text_default_none(db_session: AsyncSession) -> None:
    item = Item(user_id=1, type=ItemType.link, content="https://example.com")
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)

    assert item.embedding is None
    assert item.scraped_text is None


async def test_item_with_embedding_and_scraped_text(db_session: AsyncSession) -> None:
    vector = [0.01 * i for i in range(EMBEDDING_DIM)]
    item = Item(
        user_id=42,
        type=ItemType.link,
        content="https://example.com",
        scraped_text="Full page body text.",
        embedding=vector,
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)

    result = await db_session.execute(select(Item).where(Item.id == item.id))
    stored = result.scalar_one()
    assert stored.scraped_text == "Full page body text."
    assert stored.embedding is not None
    assert len(stored.embedding) == EMBEDDING_DIM
    assert stored.embedding[0] == 0.0
    assert abs(stored.embedding[1] - 0.01) < 1e-6


async def test_idea_embedding_default_none(db_session: AsyncSession) -> None:
    item = Item(user_id=1, type=ItemType.idea, content="Build a submarine")
    db_session.add(item)
    await db_session.flush()
    idea = Idea(item_id=item.id, tags=["ocean"])
    db_session.add(idea)
    await db_session.commit()
    await db_session.refresh(idea)

    assert idea.embedding is None


async def test_idea_with_embedding(db_session: AsyncSession) -> None:
    item = Item(user_id=1, type=ItemType.idea, content="Write a novel")
    db_session.add(item)
    await db_session.flush()
    vector = [0.5] * EMBEDDING_DIM
    idea = Idea(item_id=item.id, tags=["writing"], embedding=vector)
    db_session.add(idea)
    await db_session.commit()
    await db_session.refresh(idea)

    result = await db_session.execute(select(Idea).where(Idea.id == idea.id))
    stored = result.scalar_one()
    assert stored.embedding is not None
    assert len(stored.embedding) == EMBEDDING_DIM
    assert stored.embedding[0] == 0.5


def test_embedding_dim_constant() -> None:
    assert EMBEDDING_DIM == 1536
