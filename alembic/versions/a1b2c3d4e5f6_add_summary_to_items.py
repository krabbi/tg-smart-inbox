"""add summary column to items

Revision ID: a1b2c3d4e5f6
Revises: e9a4d2b6c815
Create Date: 2026-06-02 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "e9a4d2b6c815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable summary column to items for cached AI link summaries."""
    op.add_column("items", sa.Column("summary", sa.Text(), nullable=True))


def downgrade() -> None:
    """Drop the summary column from items."""
    op.drop_column("items", "summary")
