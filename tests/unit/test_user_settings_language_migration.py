"""Tests for the language column Alembic migration module."""

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "b5c8d9e4f127_add_language_to_user_settings.py"
)


def _load() -> ModuleType:
    """Load the migration module directly from its file path."""
    spec = importlib.util.spec_from_file_location(
        "user_settings_language_migration", _MIGRATION_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_has_expected_revision_chain() -> None:
    module = _load()
    assert module.revision == "b5c8d9e4f127"
    assert module.down_revision == "98444ad48da7"


def test_upgrade_adds_language_column_with_en_default() -> None:
    module = _load()

    with patch.object(module.op, "add_column") as mock_add_column:
        module.upgrade()

    assert mock_add_column.call_count == 1
    table, column = mock_add_column.call_args.args
    assert table == "user_settings"
    assert column.name == "language"
    assert column.nullable is False
    assert column.server_default.arg == "en"
    assert column.type.length == 8


def test_downgrade_drops_language_column() -> None:
    module = _load()

    with patch.object(module.op, "drop_column") as mock_drop_column:
        module.downgrade()

    mock_drop_column.assert_called_once_with("user_settings", "language")
