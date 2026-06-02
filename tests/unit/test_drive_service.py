from unittest.mock import MagicMock, mock_open, patch

import pytest

from bot.config import Config
from bot.exceptions import DriveUploadError
from bot.services.drive_service import (
    _CATEGORY_FOLDERS,
    _USER_ROOT_KEY,
    DriveFile,
    DriveService,
)


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
        patch("bot.services.drive_service.build") as mock_build,
    ):
        svc = DriveService(make_config())

        mock_exists.assert_not_called()
        mock_load.assert_not_called()
        mock_build.assert_not_called()
        assert svc._service is None
        assert svc._folder_cache == {}


async def test_credentials_loaded_lazily_from_existing_valid_token() -> None:
    """Token file exists and credentials are valid → load from disk on first use, no flow."""
    valid_creds = MagicMock()
    valid_creds.valid = True
    valid_creds.expired = False

    with (
        patch("bot.services.drive_service.os.path.exists", return_value=True),
        patch("bot.services.drive_service.os.path.getsize", return_value=100),
        patch(
            "bot.services.drive_service.Credentials.from_authorized_user_file",
            return_value=valid_creds,
        ) as mock_load,
        patch("bot.services.drive_service.build") as mock_build,
        patch("builtins.open", mock_open()) as mock_file,
    ):
        svc = DriveService(make_config())
        await svc._ensure_service()

        mock_load.assert_called_once_with(
            "token.json", ["https://www.googleapis.com/auth/drive.file"]
        )
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
        patch("bot.services.drive_service.os.path.getsize", return_value=100),
        patch(
            "bot.services.drive_service.Credentials.from_authorized_user_file",
            return_value=expired_creds,
        ),
        patch("bot.services.drive_service.Request") as mock_request,
        patch("bot.services.drive_service.build"),
        patch("builtins.open", mock_open()) as mock_file,
    ):
        svc = DriveService(make_config())
        await svc._ensure_service()

        expired_creds.refresh.assert_called_once_with(mock_request.return_value)
        mock_file.assert_called_once_with("token.json", "w", encoding="utf-8")
        mock_file().write.assert_called_once_with('{"refreshed": true}')


async def test_raises_error_when_token_file_missing() -> None:
    """No token file on disk → DriveUploadError with hint to run drive_auth.py."""
    with (
        patch("bot.services.drive_service.os.path.exists", return_value=False),
        patch("bot.services.drive_service.Credentials.from_authorized_user_file") as mock_load,
        patch("bot.services.drive_service.build"),
    ):
        svc = DriveService(make_config())
        with pytest.raises(DriveUploadError, match="drive_auth.py"):
            await svc._ensure_service()

        mock_load.assert_not_called()


async def test_raises_error_when_token_file_empty() -> None:
    """token.json exists but is empty (e.g. created with touch) → DriveUploadError."""
    with (
        patch("bot.services.drive_service.os.path.exists", return_value=True),
        patch("bot.services.drive_service.os.path.getsize", return_value=0),
        patch("bot.services.drive_service.Credentials.from_authorized_user_file") as mock_load,
        patch("bot.services.drive_service.build"),
    ):
        svc = DriveService(make_config())
        with pytest.raises(DriveUploadError, match="drive_auth.py"):
            await svc._ensure_service()

        mock_load.assert_not_called()


async def test_raises_error_when_token_invalid_and_no_refresh_token() -> None:
    """Token file exists but creds are invalid with no refresh token → DriveUploadError."""
    bad_creds = MagicMock()
    bad_creds.valid = False
    bad_creds.expired = True
    bad_creds.refresh_token = None

    with (
        patch("bot.services.drive_service.os.path.exists", return_value=True),
        patch("bot.services.drive_service.os.path.getsize", return_value=100),
        patch(
            "bot.services.drive_service.Credentials.from_authorized_user_file",
            return_value=bad_creds,
        ),
        patch("bot.services.drive_service.build"),
    ):
        svc = DriveService(make_config())
        with pytest.raises(DriveUploadError, match="drive_auth.py"):
            await svc._ensure_service()

        bad_creds.refresh.assert_not_called()


async def test_ensure_service_caches_built_service() -> None:
    """Subsequent calls to ``_ensure_service`` reuse the cached service (no re-auth)."""
    valid_creds = MagicMock()
    valid_creds.valid = True
    valid_creds.expired = False

    with (
        patch("bot.services.drive_service.os.path.exists", return_value=True),
        patch("bot.services.drive_service.os.path.getsize", return_value=100),
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


async def test_ensure_service_raises_drive_upload_error_on_refresh_failure() -> None:
    """Refresh failures (network) are wrapped as DriveUploadError."""
    expired_creds = MagicMock()
    expired_creds.valid = False
    expired_creds.expired = True
    expired_creds.refresh_token = "stored-refresh-token"
    expired_creds.refresh.side_effect = RuntimeError("network down")

    with (
        patch("bot.services.drive_service.os.path.exists", return_value=True),
        patch("bot.services.drive_service.os.path.getsize", return_value=100),
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


async def test_upload_file_returns_drive_file() -> None:
    svc, mock_api = make_service_with_mock_api()
    mock_api.files().list().execute.return_value = {"files": [{"id": "folder-id"}]}
    mock_api.files().create().execute.return_value = {
        "id": "file-id",
        "name": "photo.jpg",
        "webViewLink": "https://drive.google.com/file/d/file-id",
    }

    result = await svc.upload_file(b"image bytes", "photo.jpg", "photo", user_id=42)

    assert isinstance(result, DriveFile)
    assert result.file_id == "file-id"
    assert result.name == "photo.jpg"
    assert "drive.google.com" in result.web_link


async def test_upload_file_uses_correct_category_folder() -> None:
    svc, mock_api = make_service_with_mock_api()
    files_mock = mock_api.files.return_value
    files_mock.list.return_value.execute.return_value = {"files": [{"id": "receipt-folder"}]}
    files_mock.create.return_value.execute.return_value = {
        "id": "f",
        "name": "receipt.jpg",
        "webViewLink": "https://drive.google.com",
    }

    await svc.upload_file(b"bytes", "receipt.jpg", "receipt", user_id=42)

    queries = [call[1]["q"] for call in files_mock.list.call_args_list]
    assert any("📄 Receipts" in q for q in queries)


async def test_upload_file_unknown_category_uses_other_folder() -> None:
    svc, mock_api = make_service_with_mock_api()
    files_mock = mock_api.files.return_value
    files_mock.list.return_value.execute.return_value = {"files": [{"id": "other-folder"}]}
    files_mock.create.return_value.execute.return_value = {
        "id": "f",
        "name": "file.bin",
        "webViewLink": "",
    }

    await svc.upload_file(b"bytes", "file.bin", "unknown_category", user_id=42)

    queries = [call[1]["q"] for call in files_mock.list.call_args_list]
    assert any("📦 Other" in q for q in queries)


async def test_upload_file_raises_drive_upload_error_on_failure() -> None:
    svc, mock_api = make_service_with_mock_api()
    mock_api.files().list().execute.side_effect = Exception("API error")

    with pytest.raises(DriveUploadError, match="Drive upload failed"):
        await svc.upload_file(b"bytes", "file.jpg", "photo", user_id=1)


async def test_upload_file_creates_per_user_root_then_category() -> None:
    """First upload for a user must look up/create ``user_{id}`` then the category folder."""
    svc, mock_api = make_service_with_mock_api()
    files_mock = mock_api.files.return_value
    # All folder lookups return empty so each parent is created fresh.
    files_mock.list.return_value.execute.return_value = {"files": []}
    # ``create`` is called for: user_42 root, 🖼️ Photos folder, then the file itself.
    files_mock.create.return_value.execute.side_effect = [
        {"id": "user-root-id"},
        {"id": "photos-folder-id"},
        {
            "id": "file-id",
            "name": "photo.jpg",
            "webViewLink": "https://drive.google.com/file/d/file-id",
        },
    ]

    await svc.upload_file(b"bytes", "photo.jpg", "photo", user_id=42)

    create_bodies = [call[1]["body"] for call in files_mock.create.call_args_list]
    assert create_bodies[0]["name"] == "user_42"
    assert create_bodies[0]["parents"] == ["root-folder-id"]
    assert create_bodies[1]["name"] == "🖼️ Photos"
    assert create_bodies[1]["parents"] == ["user-root-id"]
    assert create_bodies[2]["name"] == "photo.jpg"
    assert create_bodies[2]["parents"] == ["photos-folder-id"]


async def test_upload_file_isolates_users_into_separate_subfolders() -> None:
    """Two different users uploading the same category land in distinct ``user_{id}`` roots."""
    svc, mock_api = make_service_with_mock_api()
    files_mock = mock_api.files.return_value
    files_mock.list.return_value.execute.return_value = {"files": []}
    # user 1: user_root, photos folder, file. user 2: user_root, photos folder, file.
    files_mock.create.return_value.execute.side_effect = [
        {"id": "user1-root"},
        {"id": "user1-photos"},
        {"id": "file-1", "name": "a.jpg", "webViewLink": ""},
        {"id": "user2-root"},
        {"id": "user2-photos"},
        {"id": "file-2", "name": "b.jpg", "webViewLink": ""},
    ]

    await svc.upload_file(b"a", "a.jpg", "photo", user_id=1)
    await svc.upload_file(b"b", "b.jpg", "photo", user_id=2)

    create_names = [call[1]["body"]["name"] for call in files_mock.create.call_args_list]
    assert "user_1" in create_names
    assert "user_2" in create_names
    # The cache should now hold both per-user roots and category folders.
    assert svc._folder_cache[(1, _USER_ROOT_KEY)] == "user1-root"
    assert svc._folder_cache[(2, _USER_ROOT_KEY)] == "user2-root"
    assert svc._folder_cache[(1, "photo")] == "user1-photos"
    assert svc._folder_cache[(2, "photo")] == "user2-photos"


async def test_upload_file_caches_folder_per_user_and_category() -> None:
    """Second upload to the same (user, category) skips folder lookup/creation entirely."""
    svc, mock_api = make_service_with_mock_api()
    files_mock = mock_api.files.return_value
    files_mock.list.return_value.execute.return_value = {"files": []}
    files_mock.create.return_value.execute.side_effect = [
        {"id": "user-root"},
        {"id": "photos-folder"},
        {"id": "file-1", "name": "a.jpg", "webViewLink": ""},
        {"id": "file-2", "name": "b.jpg", "webViewLink": ""},
    ]

    await svc.upload_file(b"a", "a.jpg", "photo", user_id=7)
    list_calls_after_first = files_mock.list.call_count
    create_calls_after_first = files_mock.create.call_count

    await svc.upload_file(b"b", "b.jpg", "photo", user_id=7)

    # Second upload: no extra ``files.list`` calls (folders served from cache),
    # and only one extra ``files.create`` call — for the file itself.
    assert files_mock.list.call_count == list_calls_after_first
    assert files_mock.create.call_count == create_calls_after_first + 1


async def test_upload_file_reuses_user_root_across_categories() -> None:
    """Different categories for the same user must share a single ``user_{id}`` root."""
    svc, mock_api = make_service_with_mock_api()
    files_mock = mock_api.files.return_value
    files_mock.list.return_value.execute.return_value = {"files": []}
    files_mock.create.return_value.execute.side_effect = [
        {"id": "user-root"},
        {"id": "photos-folder"},
        {"id": "file-photo", "name": "p.jpg", "webViewLink": ""},
        {"id": "receipts-folder"},
        {"id": "file-receipt", "name": "r.jpg", "webViewLink": ""},
    ]

    await svc.upload_file(b"p", "p.jpg", "photo", user_id=99)
    await svc.upload_file(b"r", "r.jpg", "receipt", user_id=99)

    create_names = [call[1]["body"]["name"] for call in files_mock.create.call_args_list]
    # Only one ``user_99`` folder is ever created.
    assert create_names.count("user_99") == 1
    assert svc._folder_cache[(99, _USER_ROOT_KEY)] == "user-root"
    assert svc._folder_cache[(99, "photo")] == "photos-folder"
    assert svc._folder_cache[(99, "receipt")] == "receipts-folder"


async def test_upload_file_uses_existing_folders_idempotently() -> None:
    """When ``user_{id}`` and the category folder already exist on Drive, no creates run."""
    svc, mock_api = make_service_with_mock_api()
    files_mock = mock_api.files.return_value
    # First list call → existing user_3 root; second → existing 🖼️ Photos; then create file.
    files_mock.list.return_value.execute.side_effect = [
        {"files": [{"id": "existing-user-root"}]},
        {"files": [{"id": "existing-photos"}]},
    ]
    files_mock.create.return_value.execute.return_value = {
        "id": "file-id",
        "name": "p.jpg",
        "webViewLink": "https://drive.google.com",
    }

    await svc.upload_file(b"bytes", "p.jpg", "photo", user_id=3)

    # Only the file itself is created; both folders were resolved to existing IDs.
    create_bodies = [call[1]["body"] for call in files_mock.create.call_args_list]
    assert len(create_bodies) == 1
    assert create_bodies[0]["name"] == "p.jpg"
    assert create_bodies[0]["parents"] == ["existing-photos"]


def test_get_or_create_subfolder_sync_caches_after_lookup() -> None:
    """``_get_or_create_subfolder_sync`` populates the folder cache after a fresh lookup."""
    svc, mock_api = make_service_with_mock_api()
    files_mock = mock_api.files.return_value
    files_mock.list.return_value.execute.side_effect = [
        {"files": [{"id": "user-root"}]},
        {"files": [{"id": "photos"}]},
    ]

    folder_id = svc._get_or_create_subfolder_sync(mock_api, user_id=5, category="photo")

    assert folder_id == "photos"
    assert svc._folder_cache[(5, _USER_ROOT_KEY)] == "user-root"
    assert svc._folder_cache[(5, "photo")] == "photos"


def test_get_or_create_subfolder_sync_short_circuits_on_cache_hit() -> None:
    """Pre-populated cache means no Drive API calls happen at all."""
    svc, mock_api = make_service_with_mock_api()
    svc._folder_cache[(5, _USER_ROOT_KEY)] = "user-root"
    svc._folder_cache[(5, "photo")] = "cached-photos"

    folder_id = svc._get_or_create_subfolder_sync(mock_api, user_id=5, category="photo")

    assert folder_id == "cached-photos"
    mock_api.files.assert_not_called()


def test_all_categories_have_folder_mappings() -> None:
    for cat in ("receipt", "document", "screenshot", "photo", "meme", "other"):
        assert cat in _CATEGORY_FOLDERS


async def test_upload_file_quota_exhaustion_raises_drive_upload_error() -> None:
    """Drive 403 quota-exhaustion error is wrapped as DriveUploadError with a clear message."""
    svc, mock_api = make_service_with_mock_api()
    files_mock = mock_api.files.return_value
    # Folder lookups succeed so the upload attempt is reached.
    files_mock.list.return_value.execute.return_value = {"files": [{"id": "folder-id"}]}
    # Simulate Drive API quota error on the file create call.
    files_mock.create.return_value.execute.side_effect = Exception(
        "HttpError 403: User rate limit exceeded"
    )

    with pytest.raises(DriveUploadError, match="Drive upload failed"):
        await svc.upload_file(b"bytes", "photo.jpg", "photo", user_id=42)


async def test_upload_file_quota_error_message_is_user_facing() -> None:
    """DriveUploadError raised on quota exhaustion carries the original error detail."""
    svc, mock_api = make_service_with_mock_api()
    files_mock = mock_api.files.return_value
    files_mock.list.return_value.execute.return_value = {"files": [{"id": "folder-id"}]}
    quota_exc = Exception("rateLimitExceeded")
    files_mock.create.return_value.execute.side_effect = quota_exc

    with pytest.raises(DriveUploadError) as exc_info:
        await svc.upload_file(b"bytes", "doc.pdf", "document", user_id=7)

    # The handler converts DriveUploadError to a user-facing message; verify the
    # exception carries enough context for logging and the handler to act on.
    assert "Drive upload failed" in str(exc_info.value)
    assert exc_info.value.__cause__ is quota_exc
