"""replace auto-resend with auto-archive on reminders

Revision ID: f1a2c3d4e5b6
Revises: e9a4d2b6c815
Create Date: 2026-05-30 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a2c3d4e5b6"
down_revision: str | Sequence[str] | None = "e9a4d2b6c815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Rename ``auto_resend_at`` → ``auto_archive_at`` and add ``is_auto_completed``."""
    # Rename the existing scheduling column to reflect its new semantics
    # (24h auto-archive window instead of 5-minute auto-resend).
    with op.batch_alter_table("reminders") as batch:
        batch.alter_column("auto_resend_at", new_column_name="auto_archive_at")

    op.add_column(
        "reminders",
        sa.Column(
            "is_auto_completed",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    """Restore ``auto_resend_at`` and drop ``is_auto_completed``."""
    op.drop_column("reminders", "is_auto_completed")
    with op.batch_alter_table("reminders") as batch:
        batch.alter_column("auto_archive_at", new_column_name="auto_resend_at")
