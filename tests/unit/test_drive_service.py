from unittest.mock import MagicMock, mock_open, patch

import pytest

from bot.config import Config
from bot.exceptions import DriveUploadError
from bot.services.drive_service import _CATEGORY_FOLDERS, DriveFile, DriveService


def make_config() -> Config:
    return Config(
        telegram_bot_token="fake",
        anthropic_api_key="sk-ant-fake",
        google_drive_folder_id="root-folder-id",
        google_drive_credentials_file="credentials.json",
        google_drive_token_file="token.json",
    )


def make_service_with_mock_api() -> tuple[DriveService, MagicMock]:
    """Create a DriveService and pre-inject a mocked Google API service.

    Bypasses ``_ensure_service`` entirely so individual sync helpers can be exercised
    without touching OAuth/network code.
    """
    svc = DriveService(make_config())
    mock_api = MagicMock()
    svc._service = mock_api
    return svc, mock_api


def test_init_does_not_load_credentials_or_build_service() -> None:
    """``__init__`` must be free of network/IO side effects (no OAuth, no API build)."""
    with (
        patch("bot.services.drive_service.os.path.exists") as mock_exists,
        patch("bot.services.drive_service.Credentials.from_authorized_user_file") as mock_load,
        patch("bot.services.drive_service.InstalledAppFlow") as mock_flow,
        patch("bot.services.drive_service.build") as mock_build,
    ):
        svc = DriveService(make_config())

        mock_exists.assert_not_called()
        mock_load.assert_not_called()
        mock_flow.from_client_secrets_file.assert_not_called()
        mock_build.assert_not_called()
        assert svc._service is None


async def test_credentials_loaded_lazily_from_existing_valid_token() -> None:
    """Token file exists and credentials are valid → load from disk on first use, no flow."""
    valid_creds = MagicMock()
    valid_creds.valid = True
    valid_creds.expired = False

    with (
        patch("bot.services.drive_service.os.path.exists", return_value=True),
        patch(
            "bot.services.drive_service.Credentials.from_authorized_user_file",
            return_value=valid_creds,
        ) as mock_load,
        patch("bot.services.drive_service.InstalledAppFlow") as mock_flow,
        patch("bot.services.drive_service.build") as mock_build,
        patch("builtins.open", mock_open()) as mock_file,
    ):
        svc = DriveService(make_config())
        await svc._ensure_service()

        mock_load.assert_called_once_with(
            "token.json", ["https://www.googleapis.com/auth/drive.file"]
        )
        mock_flow.from_client_secrets_file.assert_not_called()
        mock_file.assert_not_called()  # no rewrite when creds are already valid
        mock_build.assert_called_once()


async def test_credentials_refreshed_when_expired() -> None:
    """Token exists but is expired → refresh via stored refresh token, persist to disk."""
    expired_creds = MagicMock()
    expired_creds.valid = False
    expired_creds.expired = True
    expired_creds.refresh_token = "stored-refresh-token"
    expired_creds.to_json.return_value = '{"refreshed": true}'

    with (
        patch("bot.services.drive_service.os.path.exists", return_value=True),
        patch(
            "bot.services.drive_service.Credentials.from_authorized_user_file",
            return_value=expired_creds,
        ),
        patch("bot.services.drive_service.InstalledAppFlow") as mock_flow,
        patch("bot.services.drive_service.Request") as mock_request,
        patch("bot.services.drive_service.build"),
        patch("builtins.open", mock_open()) as mock_file,
    ):
        svc = DriveService(make_config())
        await svc._ensure_service()

        expired_creds.refresh.assert_called_once_with(mock_request.return_value)
        mock_flow.from_client_secrets_file.assert_not_called()
        mock_file.assert_called_once_with("token.json", "w", encoding="utf-8")
        mock_file().write.assert_called_once_with('{"refreshed": true}')


async def test_oauth_flow_runs_when_token_file_missing() -> None:
    """No token file on disk → run InstalledAppFlow and save the resulting token."""
    new_creds = MagicMock()
    new_creds.to_json.return_value = '{"new": true}'
    flow_instance = MagicMock()
    flow_instance.run_local_server.return_value = new_creds

    with (
        patch("bot.services.drive_service.os.path.exists", return_value=False),
        patch("bot.services.drive_service.Credentials.from_authorized_user_file") as mock_load,
        patch("bot.services.drive_service.InstalledAppFlow") as mock_flow_cls,
        patch("bot.services.drive_service.build"),
        patch("builtins.open", mock_open()) as mock_file,
    ):
        mock_flow_cls.from_client_secrets_file.return_value = flow_instance

        svc = DriveService(make_config())
        await svc._ensure_service()

        mock_load.assert_not_called()
        mock_flow_cls.from_client_secrets_file.assert_called_once_with(
            "credentials.json", ["https://www.googleapis.com/auth/drive.file"]
        )
        flow_instance.run_local_server.assert_called_once_with(port=0)
        mock_file.assert_called_once_with("token.json", "w", encoding="utf-8")
        mock_file().write.assert_called_once_with('{"new": true}')


async def test_oauth_flow_runs_when_token_invalid_and_no_refresh_token() -> None:
    """Token file exists but creds are invalid with no refresh token → run flow."""
    bad_creds = MagicMock()
    bad_creds.valid = False
    bad_creds.expired = True
    bad_creds.refresh_token = None
    new_creds = MagicMock()
    new_creds.to_json.return_value = '{"new": true}'
    flow_instance = MagicMock()
    flow_instance.run_local_server.return_value = new_creds

    with (
        patch("bot.services.drive_service.os.path.exists", return_value=True),
        patch(
            "bot.services.drive_service.Credentials.from_authorized_user_file",
            return_value=bad_creds,
        ),
        patch("bot.services.drive_service.InstalledAppFlow") as mock_flow_cls,
        patch("bot.services.drive_service.build"),
        patch("builtins.open", mock_open()),
    ):
        mock_flow_cls.from_client_secrets_file.return_value = flow_instance

        svc = DriveService(make_config())
        await svc._ensure_service()

        bad_creds.refresh.assert_not_called()
        mock_flow_cls.from_client_secrets_file.assert_called_once()
        flow_instance.run_local_server.assert_called_once_with(port=0)


async def test_ensure_service_caches_built_service() -> None:
    """Subsequent calls to ``_ensure_service`` reuse the cached service (no re-auth)."""
    valid_creds = MagicMock()
    valid_creds.valid = True
    valid_creds.expired = False

    with (
        patch("bot.services.drive_service.os.path.exists", return_value=True),
        patch(
            "bot.services.drive_service.Credentials.from_authorized_user_file",
            return_value=valid_creds,
        ) as mock_load,
        patch("bot.services.drive_service.build") as mock_build,
    ):
        svc = DriveService(make_config())
        first = await svc._ensure_service()
        second = await svc._ensure_service()

        assert first is second
        mock_load.assert_called_once()
        mock_build.assert_called_once()


async def test_ensure_service_raises_drive_upload_error_on_oauth_failure() -> None:
    """OAuth flow failures (network/no browser) are wrapped as DriveUploadError."""
    flow_instance = MagicMock()
    flow_instance.run_local_server.side_effect = RuntimeError("no display")

    with (
        patch("bot.services.drive_service.os.path.exists", return_value=False),
        patch("bot.services.drive_service.InstalledAppFlow") as mock_flow_cls,
        patch("bot.services.drive_service.build"),
    ):
        mock_flow_cls.from_client_secrets_file.return_value = flow_instance

        svc = DriveService(make_config())
        with pytest.raises(DriveUploadError, match="OAuth flow failed"):
            await svc._ensure_service()


async def test_ensure_service_raises_drive_upload_error_on_refresh_failure() -> None:
    """Refresh failures (network) are wrapped as DriveUploadError."""
    expired_creds = MagicMock()
    expired_creds.valid = False
    expired_creds.expired = True
    expired_creds.refresh_token = "stored-refresh-token"
    expired_creds.refresh.side_effect = RuntimeError("network down")

    with (
        patch("bot.services.drive_service.os.path.exists", return_value=True),
        patch(
            "bot.services.drive_service.Credentials.from_authorized_user_file",
            return_value=expired_creds,
        ),
        patch("bot.services.drive_service.Request"),
        patch("bot.services.drive_service.build"),
    ):
        svc = DriveService(make_config())
        with pytest.raises(DriveUploadError, match="refresh"):
            await svc._ensure_service()


async def test_get_or_create_folder_returns_existing() -> None:
    svc, mock_api = make_service_with_mock_api()
    mock_api.files().list().execute.return_value = {"files": [{"id": "existing-id"}]}

    result = await svc.get_or_create_folder("📄 Receipts")

    assert result == "existing-id"
    mock_api.files().create.assert_not_called()


async def test_get_or_create_folder_creates_new() -> None:
    svc, mock_api = make_service_with_mock_api()
    mock_api.files().list().execute.return_value = {"files": []}
    mock_api.files().create().execute.return_value = {"id": "new-folder-id"}

    result = await svc.get_or_create_folder("📦 Other")

    assert result == "new-folder-id"


async def test_upload_returns_drive_file() -> None:
    svc, mock_api = make_service_with_mock_api()
    mock_api.files().list().execute.return_value = {"files": [{"id": "folder-id"}]}
    mock_api.files().create().execute.return_value = {
        "id": "file-id",
        "name": "photo.jpg",
        "webViewLink": "https://drive.google.com/file/d/file-id",
    }

    result = await svc.upload(b"image bytes", "photo.jpg", "photo")

    assert isinstance(result, DriveFile)
    assert result.file_id == "file-id"
    assert result.name == "photo.jpg"
    assert "drive.google.com" in result.web_link


async def test_upload_uses_correct_category_folder() -> None:
    svc, mock_api = make_service_with_mock_api()
    files_mock = mock_api.files.return_value
    files_mock.list.return_value.execute.return_value = {"files": [{"id": "receipt-folder"}]}
    files_mock.create.return_value.execute.return_value = {
        "id": "f",
        "name": "receipt.jpg",
        "webViewLink": "https://drive.google.com",
    }

    await svc.upload(b"bytes", "receipt.jpg", "receipt")

    list_call = files_mock.list.call_args_list[0]
    query = list_call[1]["q"]
    assert "📄 Receipts" in query


async def test_upload_unknown_category_uses_other_folder() -> None:
    svc, mock_api = make_service_with_mock_api()
    files_mock = mock_api.files.return_value
    files_mock.list.return_value.execute.return_value = {"files": [{"id": "other-folder"}]}
    files_mock.create.return_value.execute.return_value = {
        "id": "f",
        "name": "file.bin",
        "webViewLink": "",
    }

    await svc.upload(b"bytes", "file.bin", "unknown_category")

    list_call = files_mock.list.call_args_list[0]
    query = list_call[1]["q"]
    assert "📦 Other" in query


async def test_upload_raises_drive_upload_error_on_failure() -> None:
    svc, mock_api = make_service_with_mock_api()
    mock_api.files().list().execute.side_effect = Exception("API error")

    with pytest.raises(DriveUploadError, match="Drive upload failed"):
        await svc.upload(b"bytes", "file.jpg", "photo")


def test_all_categories_have_folder_mappings() -> None:
    for cat in ("receipt", "document", "screenshot", "photo", "meme", "other"):
        assert cat in _CATEGORY_FOLDERS
