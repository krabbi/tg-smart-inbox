"""add complexity and effort to ideas

Revision ID: ff17af10c29d
Revises: 5722873803ca
Create Date: 2026-04-06 19:40:15.345162

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ff17af10c29d"
down_revision: str | Sequence[str] | None = "5722873803ca"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create PostgreSQL enum types explicitly before using them in columns.
    # op.add_column does not CREATE TYPE automatically on PostgreSQL.
    complexity_enum = sa.Enum("simple", "medium", "complex", name="ideacomplexity")
    effort_enum = sa.Enum("quick", "halfday", "day", "longterm", name="ideaeffort")
    complexity_enum.create(op.get_bind(), checkfirst=True)
    effort_enum.create(op.get_bind(), checkfirst=True)

    op.add_column("ideas", sa.Column("complexity", complexity_enum, nullable=True))
    op.add_column("ideas", sa.Column("effort", effort_enum, nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("ideas", "effort")
    op.drop_column("ideas", "complexity")

    # Drop PostgreSQL enum types after the columns are gone.
    sa.Enum(name="ideacomplexity").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="ideaeffort").drop(op.get_bind(), checkfirst=True)
