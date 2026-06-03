"""Tests for the ``add summary column to items`` Alembic migration."""

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "a1b2c3d4e5f6_add_summary_to_items.py"
)


def _load() -> ModuleType:
    """Load the migration module directly from its file path."""
    spec = importlib.util.spec_from_file_location("summary_migration", _MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_has_expected_revision_chain() -> None:
    """Migration sits on top of the title-column migration."""
    module = _load()
    assert module.revision == "a1b2c3d4e5f6"
    assert module.down_revision == "e9a4d2b6c815"


def test_upgrade_adds_summary_column_to_items() -> None:
    """upgrade() adds a single nullable Text column ``summary`` on the items table."""
    module = _load()

    with patch.object(module.op, "add_column") as mock_add_column:
        module.upgrade()

    assert mock_add_column.call_count == 1
    table_arg, column_arg = mock_add_column.call_args.args
    assert table_arg == "items"
    assert column_arg.name == "summary"
    assert column_arg.nullable is True


def test_downgrade_drops_summary_column() -> None:
    """downgrade() removes the summary column it added."""
    module = _load()

    with patch.object(module.op, "drop_column") as mock_drop_column:
        module.downgrade()

    mock_drop_column.assert_called_once_with("items", "summary")


def test_upgrade_does_not_touch_other_tables() -> None:
    """The migration only modifies ``items`` — no execute/SQL on the side."""
    module = _load()

    with (
        patch.object(module.op, "add_column") as mock_add_column,
        patch.object(module.op, "execute") as mock_execute,
    ):
        module.upgrade()

    mock_execute.assert_not_called()
    assert all(call.args[0] == "items" for call in mock_add_column.call_args_list)


def test_upgrade_is_callable_with_real_op_bind_mock() -> None:
    """Sanity check: upgrade() does not fall over with a fully mocked op API."""
    module = _load()
    with (
        patch.object(module.op, "get_bind", return_value=MagicMock()),
        patch.object(module.op, "add_column"),
    ):
        module.upgrade()
