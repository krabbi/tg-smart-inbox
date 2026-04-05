import enum

from sqlalchemy import BigInteger, Enum, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base, TimestampMixin, UUIDMixin


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

    reminders: Mapped[list["Reminder"]] = relationship(  # noqa: F821
        "Reminder", back_populates="item", cascade="all, delete-orphan"
    )
    idea: Mapped["Idea | None"] = relationship(  # noqa: F821
        "Idea", back_populates="item", cascade="all, delete-orphan", uselist=False
    )
