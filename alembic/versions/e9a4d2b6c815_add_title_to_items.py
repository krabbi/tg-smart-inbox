"""add title column to items

Revision ID: e9a4d2b6c815
Revises: c3e7f2a1d8b4
Create Date: 2026-05-06 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e9a4d2b6c815"
down_revision: str | Sequence[str] | None = "c3e7f2a1d8b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable title column to items for cached link page titles."""
    op.add_column("items", sa.Column("title", sa.Text(), nullable=True))


def downgrade() -> None:
    """Drop the title column from items."""
    op.drop_column("items", "title")
