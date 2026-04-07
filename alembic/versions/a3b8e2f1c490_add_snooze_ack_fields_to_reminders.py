"""add snooze/ack fields to reminders

Revision ID: a3b8e2f1c490
Revises: ff17af10c29d
Create Date: 2026-04-06 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3b8e2f1c490"
down_revision: str | Sequence[str] | None = "ff17af10c29d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add is_acknowledged, snooze_count, and auto_resend_at columns to reminders."""
    op.add_column(
        "reminders",
        sa.Column("is_acknowledged", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "reminders",
        sa.Column("snooze_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "reminders",
        sa.Column("auto_resend_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Remove snooze/ack fields from reminders."""
    op.drop_column("reminders", "auto_resend_at")
    op.drop_column("reminders", "snooze_count")
    op.drop_column("reminders", "is_acknowledged")
