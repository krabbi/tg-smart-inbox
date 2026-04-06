from unittest.mock import MagicMock, patch

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
    )


def make_service_with_mock_api() -> tuple[DriveService, MagicMock]:
    """Create a DriveService with a mocked Google API service."""
    with (
        patch("bot.services.drive_service.service_account.Credentials.from_service_account_file"),
        patch("bot.services.drive_service.build") as mock_build,
    ):
        mock_api = MagicMock()
        mock_build.return_value = mock_api
        svc = DriveService(make_config())
        return svc, mock_api


def test_get_or_create_folder_returns_existing() -> None:
    svc, mock_api = make_service_with_mock_api()
    mock_api.files().list().execute.return_value = {"files": [{"id": "existing-id"}]}

    result = svc.get_or_create_folder("📄 Receipts")

    assert result == "existing-id"
    mock_api.files().create.assert_not_called()


def test_get_or_create_folder_creates_new() -> None:
    svc, mock_api = make_service_with_mock_api()
    mock_api.files().list().execute.return_value = {"files": []}
    mock_api.files().create().execute.return_value = {"id": "new-folder-id"}

    result = svc.get_or_create_folder("📦 Other")

    assert result == "new-folder-id"


def test_upload_returns_drive_file() -> None:
    svc, mock_api = make_service_with_mock_api()
    mock_api.files().list().execute.return_value = {"files": [{"id": "folder-id"}]}
    mock_api.files().create().execute.return_value = {
        "id": "file-id",
        "name": "photo.jpg",
        "webViewLink": "https://drive.google.com/file/d/file-id",
    }

    result = svc.upload(b"image bytes", "photo.jpg", "photo")

    assert isinstance(result, DriveFile)
    assert result.file_id == "file-id"
    assert result.name == "photo.jpg"
    assert "drive.google.com" in result.web_link


def test_upload_uses_correct_category_folder() -> None:
    svc, mock_api = make_service_with_mock_api()
    files_mock = mock_api.files.return_value
    files_mock.list.return_value.execute.return_value = {"files": [{"id": "receipt-folder"}]}
    files_mock.create.return_value.execute.return_value = {
        "id": "f",
        "name": "receipt.jpg",
        "webViewLink": "https://drive.google.com",
    }

    svc.upload(b"bytes", "receipt.jpg", "receipt")

    list_call = files_mock.list.call_args_list[0]
    query = list_call[1]["q"]
    assert "📄 Receipts" in query


def test_upload_unknown_category_uses_other_folder() -> None:
    svc, mock_api = make_service_with_mock_api()
    files_mock = mock_api.files.return_value
    files_mock.list.return_value.execute.return_value = {"files": [{"id": "other-folder"}]}
    files_mock.create.return_value.execute.return_value = {
        "id": "f",
        "name": "file.bin",
        "webViewLink": "",
    }

    svc.upload(b"bytes", "file.bin", "unknown_category")

    list_call = files_mock.list.call_args_list[0]
    query = list_call[1]["q"]
    assert "📦 Other" in query


def test_upload_raises_drive_upload_error_on_failure() -> None:
    svc, mock_api = make_service_with_mock_api()
    mock_api.files().list().execute.side_effect = Exception("API error")

    with pytest.raises(DriveUploadError, match="Drive upload failed"):
        svc.upload(b"bytes", "file.jpg", "photo")


def test_all_categories_have_folder_mappings() -> None:
    for cat in ("receipt", "document", "screenshot", "photo", "meme", "other"):
        assert cat in _CATEGORY_FOLDERS
