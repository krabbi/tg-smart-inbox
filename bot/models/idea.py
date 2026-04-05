import uuid

from sqlalchemy import JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base


class Idea(Base):
    __tablename__ = "ideas"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id"), nullable=False, unique=True)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    item: Mapped["Item"] = relationship("Item", back_populates="idea")  # noqa: F821
