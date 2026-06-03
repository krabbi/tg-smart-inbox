"""merge heads

Revision ID: b0e1f2a3c4d5
Revises: a1b2c3d4e5f6, f1a2c3d4e5b6
Create Date: 2026-06-03 00:00:00.000000

"""

from collections.abc import Sequence

revision: str = "b0e1f2a3c4d5"
down_revision: str | Sequence[str] | None = ("a1b2c3d4e5f6", "f1a2c3d4e5b6")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
