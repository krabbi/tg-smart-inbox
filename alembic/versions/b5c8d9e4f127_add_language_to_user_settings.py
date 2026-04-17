"""add language column to user_settings

Revision ID: b5c8d9e4f127
Revises: 98444ad48da7
Create Date: 2026-04-17 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5c8d9e4f127"
down_revision: str | Sequence[str] | None = "98444ad48da7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add language column to user_settings with server default 'en'."""
    op.add_column(
        "user_settings",
        sa.Column(
            "language",
            sa.String(length=8),
            nullable=False,
            server_default="en",
        ),
    )


def downgrade() -> None:
    """Drop language column from user_settings."""
    op.drop_column("user_settings", "language")
