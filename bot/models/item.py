import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base


class ItemType(enum.Enum):
    link = "link"
    note = "note"
    task = "task"
    media = "media"
    idea = "idea"


class Item(Base):
    __tablename__ = "items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    type: Mapped[ItemType] = mapped_column(Enum(ItemType), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    reminders: Mapped[list["Reminder"]] = relationship(  # noqa: F821
        "Reminder", back_populates="item", cascade="all, delete-orphan"
    )
    idea: Mapped["Idea | None"] = relationship(  # noqa: F821
        "Idea", back_populates="item", cascade="all, delete-orphan", uselist=False
    )
