import uuid

from sqlalchemy import JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base, UUIDMixin


class Idea(UUIDMixin, Base):
    __tablename__ = "ideas"

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    item: Mapped["Item"] = relationship("Item", back_populates="idea")  # noqa: F821
