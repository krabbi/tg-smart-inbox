import enum
import uuid

from sqlalchemy import JSON, Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base, UUIDMixin


class IdeaComplexity(enum.Enum):
    """Estimated complexity of an idea."""

    simple = "simple"
    medium = "medium"
    complex = "complex"


class IdeaEffort(enum.Enum):
    """Estimated time effort to execute an idea."""

    quick = "quick"  # < 1 hour
    halfday = "halfday"  # 1–4 hours
    day = "day"  # 4–8 hours
    longterm = "longterm"  # days or more


class Idea(UUIDMixin, Base):
    __tablename__ = "ideas"

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    complexity: Mapped[IdeaComplexity | None] = mapped_column(Enum(IdeaComplexity), nullable=True)
    effort: Mapped[IdeaEffort | None] = mapped_column(Enum(IdeaEffort), nullable=True)

    item: Mapped["Item"] = relationship("Item", back_populates="idea")  # noqa: F821
