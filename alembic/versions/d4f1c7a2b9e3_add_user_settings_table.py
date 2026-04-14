"""add user_settings table

Revision ID: d4f1c7a2b9e3
Revises: a3b8e2f1c490
Create Date: 2026-04-14 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4f1c7a2b9e3"
down_revision: str | Sequence[str] | None = "a3b8e2f1c490"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create user_settings table for per-user preferences (timezone, etc.)."""
    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "timezone",
            sa.String(length=64),
            nullable=False,
            server_default="UTC",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    """Drop user_settings table."""
    op.drop_table("user_settings")
