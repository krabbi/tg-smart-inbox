"""Tests for the ``replace auto-resend with auto-archive`` Alembic migration."""

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "f1a2c3d4e5b6_replace_auto_resend_with_auto_archive.py"
)


def _load() -> ModuleType:
    """Load the migration module directly from its file path."""
    spec = importlib.util.spec_from_file_location("auto_archive_migration", _MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_has_expected_revision_chain() -> None:
    """Migration sits on top of the title migration."""
    module = _load()
    assert module.revision == "f1a2c3d4e5b6"
    assert module.down_revision == "e9a4d2b6c815"


def test_upgrade_renames_auto_resend_at_and_adds_is_auto_completed() -> None:
    """upgrade() renames the timer column and adds the ``is_auto_completed`` flag."""
    module = _load()

    batch_proxy = MagicMock()

    class _BatchCtx:
        def __enter__(self_inner) -> MagicMock:  # noqa: N805
            return batch_proxy

        def __exit__(self_inner, *_args: object) -> None:  # noqa: N805
            return None

    with (
        patch.object(module.op, "batch_alter_table", return_value=_BatchCtx()) as mock_batch,
        patch.object(module.op, "add_column") as mock_add_column,
    ):
        module.upgrade()

    mock_batch.assert_called_once_with("reminders")
    batch_proxy.alter_column.assert_called_once_with(
        "auto_resend_at", new_column_name="auto_archive_at"
    )

    assert mock_add_column.call_count == 1
    table_arg, column_arg = mock_add_column.call_args.args
    assert table_arg == "reminders"
    assert column_arg.name == "is_auto_completed"
    assert column_arg.nullable is False


def test_downgrade_reverses_the_changes() -> None:
    """downgrade() drops the new flag and renames the timer column back."""
    module = _load()

    batch_proxy = MagicMock()

    class _BatchCtx:
        def __enter__(self_inner) -> MagicMock:  # noqa: N805
            return batch_proxy

        def __exit__(self_inner, *_args: object) -> None:  # noqa: N805
            return None

    with (
        patch.object(module.op, "batch_alter_table", return_value=_BatchCtx()),
        patch.object(module.op, "drop_column") as mock_drop_column,
    ):
        module.downgrade()

    mock_drop_column.assert_called_once_with("reminders", "is_auto_completed")
    batch_proxy.alter_column.assert_called_once_with(
        "auto_archive_at", new_column_name="auto_resend_at"
    )
