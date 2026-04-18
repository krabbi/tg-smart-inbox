"""change embedding dim 1536 to 1024 (Voyage AI)

Revision ID: c3e7f2a1d8b4
Revises: b5c8d9e4f127
Create Date: 2026-04-18 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision: str = "c3e7f2a1d8b4"
down_revision: str | Sequence[str] | None = "b5c8d9e4f127"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_DIM = 1536
NEW_DIM = 1024


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute("DROP INDEX IF EXISTS ix_items_embedding")
        op.execute("DROP INDEX IF EXISTS ix_ideas_embedding")

    # pgvector does not support ALTER COLUMN for vector type — drop and recreate
    op.drop_column("items", "embedding")
    op.drop_column("ideas", "embedding")
    op.add_column("items", sa.Column("embedding", Vector(NEW_DIM), nullable=True))
    op.add_column("ideas", sa.Column("embedding", Vector(NEW_DIM), nullable=True))

    if is_postgres:
        op.execute(
            "CREATE INDEX ix_items_embedding ON items "
            "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
        )
        op.execute(
            "CREATE INDEX ix_ideas_embedding ON ideas "
            "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute("DROP INDEX IF EXISTS ix_items_embedding")
        op.execute("DROP INDEX IF EXISTS ix_ideas_embedding")

    op.drop_column("items", "embedding")
    op.drop_column("ideas", "embedding")
    op.add_column("items", sa.Column("embedding", Vector(OLD_DIM), nullable=True))
    op.add_column("ideas", sa.Column("embedding", Vector(OLD_DIM), nullable=True))

    if is_postgres:
        op.execute(
            "CREATE INDEX ix_items_embedding ON items "
            "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
        )
        op.execute(
            "CREATE INDEX ix_ideas_embedding ON ideas "
            "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
        )
