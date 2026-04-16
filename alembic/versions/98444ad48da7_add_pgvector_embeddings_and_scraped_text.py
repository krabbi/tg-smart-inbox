"""add pgvector embeddings and scraped_text

Revision ID: 98444ad48da7
Revises: d4f1c7a2b9e3
Create Date: 2026-04-16 16:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "98444ad48da7"
down_revision: str | Sequence[str] | None = "d4f1c7a2b9e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 1536


def upgrade() -> None:
    """Enable pgvector and add embedding/scraped_text columns to items and ideas."""
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # pgvector lives only on PostgreSQL. On SQLite (used in tests) we still add the
    # columns — the driver silently treats the VECTOR type as BLOB/TEXT — but we skip
    # the extension and the ivfflat index, both of which are Postgres-only.
    if is_postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.add_column("items", sa.Column("scraped_text", sa.Text(), nullable=True))
    op.add_column("items", sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True))
    op.add_column("ideas", sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True))

    if is_postgres:
        # ivfflat with cosine ops — good default for semantic search over OpenAI-style
        # embeddings. lists=100 is a conservative starting point for small tables;
        # tune later once real data volumes are known.
        op.execute(
            "CREATE INDEX ix_items_embedding ON items "
            "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
        )
        op.execute(
            "CREATE INDEX ix_ideas_embedding ON ideas "
            "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
        )


def downgrade() -> None:
    """Drop embedding/scraped_text columns and their pgvector indexes."""
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute("DROP INDEX IF EXISTS ix_ideas_embedding")
        op.execute("DROP INDEX IF EXISTS ix_items_embedding")

    op.drop_column("ideas", "embedding")
    op.drop_column("items", "embedding")
    op.drop_column("items", "scraped_text")

    # Leave the `vector` extension in place — other databases or apps in the same
    # cluster may depend on it, and recreating it is cheap.
