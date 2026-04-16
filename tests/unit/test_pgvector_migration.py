"""Tests for the pgvector Alembic migration module."""

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "98444ad48da7_add_pgvector_embeddings_and_scraped_text.py"
)


def _load() -> ModuleType:
    """Load the migration module directly from its file path."""
    spec = importlib.util.spec_from_file_location("pgvector_migration", _MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_has_expected_revision_chain() -> None:
    module = _load()
    assert module.revision == "98444ad48da7"
    assert module.down_revision == "d4f1c7a2b9e3"
    assert module.EMBEDDING_DIM == 1536


def test_upgrade_on_postgres_creates_extension_columns_and_indexes() -> None:
    module = _load()
    bind = MagicMock()
    bind.dialect.name = "postgresql"

    with (
        patch.object(module.op, "get_bind", return_value=bind),
        patch.object(module.op, "execute") as mock_execute,
        patch.object(module.op, "add_column") as mock_add_column,
    ):
        module.upgrade()

    executed_sql = [call.args[0] for call in mock_execute.call_args_list]
    assert "CREATE EXTENSION IF NOT EXISTS vector" in executed_sql
    assert any("ix_items_embedding" in sql and "ivfflat" in sql for sql in executed_sql)
    assert any("ix_ideas_embedding" in sql and "vector_cosine_ops" in sql for sql in executed_sql)

    added_columns = [(call.args[0], call.args[1].name) for call in mock_add_column.call_args_list]
    assert ("items", "scraped_text") in added_columns
    assert ("items", "embedding") in added_columns
    assert ("ideas", "embedding") in added_columns


def test_upgrade_on_sqlite_skips_extension_and_indexes() -> None:
    module = _load()
    bind = MagicMock()
    bind.dialect.name = "sqlite"

    with (
        patch.object(module.op, "get_bind", return_value=bind),
        patch.object(module.op, "execute") as mock_execute,
        patch.object(module.op, "add_column") as mock_add_column,
    ):
        module.upgrade()

    # No CREATE EXTENSION, no CREATE INDEX — but columns still get added so tests
    # can run the migration against SQLite.
    assert mock_execute.call_count == 0
    assert mock_add_column.call_count == 3


def test_downgrade_on_postgres_drops_indexes_and_columns() -> None:
    module = _load()
    bind = MagicMock()
    bind.dialect.name = "postgresql"

    with (
        patch.object(module.op, "get_bind", return_value=bind),
        patch.object(module.op, "execute") as mock_execute,
        patch.object(module.op, "drop_column") as mock_drop_column,
    ):
        module.downgrade()

    executed_sql = [call.args[0] for call in mock_execute.call_args_list]
    assert any("DROP INDEX IF EXISTS ix_ideas_embedding" in sql for sql in executed_sql)
    assert any("DROP INDEX IF EXISTS ix_items_embedding" in sql for sql in executed_sql)

    dropped = [(call.args[0], call.args[1]) for call in mock_drop_column.call_args_list]
    assert dropped == [
        ("ideas", "embedding"),
        ("items", "embedding"),
        ("items", "scraped_text"),
    ]


def test_downgrade_on_sqlite_skips_index_drops() -> None:
    module = _load()
    bind = MagicMock()
    bind.dialect.name = "sqlite"

    with (
        patch.object(module.op, "get_bind", return_value=bind),
        patch.object(module.op, "execute") as mock_execute,
        patch.object(module.op, "drop_column") as mock_drop_column,
    ):
        module.downgrade()

    assert mock_execute.call_count == 0
    assert mock_drop_column.call_count == 3
