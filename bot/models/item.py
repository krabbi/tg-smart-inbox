import enum

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Enum, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base, TimestampMixin, UUIDMixin

# Fixed DB-column dimensionality; the matching Config.embedding_dim setting is the
# source of truth for services that generate embeddings. Changing this requires a
# new Alembic migration.
EMBEDDING_DIM = 1024


class ItemType(enum.Enum):
    link = "link"
    note = "note"
    task = "task"
    media = "media"
    idea = "idea"


class Item(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "items"

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    type: Mapped[ItemType] = mapped_column(Enum(ItemType), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Article title for links — extracted from <og:title> or <title> at save time.
    # Used in /list, /search, /reminders and reminder push notifications instead of
    # the bare URL when present. Always None for non-link items.
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Full extracted page text for links — cached so we don't re-scrape for re-embedding.
    scraped_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Vector embedding for semantic search; populated lazily by a background job.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)

    reminders: Mapped[list["Reminder"]] = relationship(  # noqa: F821
        "Reminder", back_populates="item", cascade="all, delete-orphan"
    )
    idea: Mapped["Idea | None"] = relationship(  # noqa: F821
        "Idea", back_populates="item", cascade="all, delete-orphan", uselist=False
    )
