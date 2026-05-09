import asyncio
import io
import logging
import os
from dataclasses import dataclass
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from bot.config import Config
from bot.exceptions import DriveUploadError

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/drive.file"]

_CATEGORY_FOLDERS: dict[str, str] = {
    "receipt": "📄 Receipts",
    "document": "📁 Documents",
    "screenshot": "🖥️ Screenshots",
    "photo": "🖼️ Photos",
    "meme": "😄 Memes",
    "other": "📦 Other",
}

# Cache marker used internally to remember the per-user root folder id.
# Stored in the same dict as category folders, keyed by ``(user_id, _USER_ROOT_KEY)``.
_USER_ROOT_KEY = "__user_root__"


@dataclass(frozen=True)
class DriveFile:
    """Metadata for an uploaded Drive file."""

    file_id: str
    name: str
    web_link: str


class DriveService:
    """Upload files to Google Drive and manage per-user category subfolders."""

    def __init__(self, config: Config) -> None:
        """Store configuration. Credential loading is deferred to first use."""
        self._root_folder_id = config.google_drive_folder_id
        self._credentials_file = config.google_drive_credentials_file
        self._token_file = config.google_drive_token_file
        self._service: Any | None = None
        self._init_lock = asyncio.Lock()
        # Folder id cache keyed by (user_id, category). The special category
        # ``_USER_ROOT_KEY`` stores the per-user root folder id itself.
        self._folder_cache: dict[tuple[int, str], str] = {}

    def _load_credentials(self) -> Credentials:
        """Load OAuth user credentials, refreshing or running the auth flow as needed.

        On first run (no token file): runs the InstalledAppFlow to obtain credentials,
        which requires a browser-based user consent. The resulting token (with refresh
        token) is persisted to ``google_drive_token_file`` for reuse.

        On subsequent runs: loads the token from disk and refreshes it automatically
        when expired, using the stored refresh token.

        Raises DriveUploadError when the OAuth flow or refresh fails (network error,
        no browser available, missing credentials file, etc.).
        """
        creds: Credentials | None = None
        if os.path.exists(self._token_file) and os.path.getsize(self._token_file) > 0:
            creds = Credentials.from_authorized_user_file(self._token_file, _SCOPES)

        if creds is None or not creds.valid:
            if creds is not None and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as exc:
                    logger.exception("Failed to refresh Google Drive credentials")
                    raise DriveUploadError(
                        f"Failed to refresh Google Drive credentials: {exc}"
                    ) from exc
            else:
                raise DriveUploadError(
                    f"Google Drive token missing or invalid: {self._token_file}. "
                    "Run the one-time auth command on the server: "
                    "docker compose run --rm -it bot python scripts/drive_auth.py"
                )
            with open(self._token_file, "w", encoding="utf-8") as token_fp:
                token_fp.write(creds.to_json())

        return creds

    def _build_service_sync(self) -> Any:
        """Synchronously build an authenticated Google Drive API service."""
        credentials = self._load_credentials()
        return build("drive", "v3", credentials=credentials, cache_discovery=False)

    async def _ensure_service(self) -> Any:
        """Lazily build the Drive API service on first use without blocking the loop.

        OAuth credential loading and service construction are CPU/IO bound and may
        block on network or browser-based consent. We offload the work to a worker
        thread via :func:`asyncio.to_thread` and guard concurrent first-time
        initialization with a per-instance lock so two awaiting handlers don't run
        the OAuth flow twice.
        """
        if self._service is not None:
            return self._service
        async with self._init_lock:
            if self._service is None:
                self._service = await asyncio.to_thread(self._build_service_sync)
        return self._service

    def _get_or_create_folder_sync(self, service: Any, name: str, parent_id: str | None) -> str:
        """Synchronously look up or create a folder under ``parent_id`` (or root)."""
        parent = parent_id or self._root_folder_id
        # Escape single quotes per Drive API query syntax
        escaped_name = name.replace("'", "\\'")
        query = (
            f"name='{escaped_name}' and mimeType='application/vnd.google-apps.folder'"
            f" and '{parent}' in parents and trashed=false"
        )
        results = service.files().list(q=query, fields="files(id, name)", spaces="drive").execute()
        files = results.get("files", [])
        if files:
            return files[0]["id"]

        folder_metadata = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent],
        }
        folder = service.files().create(body=folder_metadata, fields="id").execute()
        return folder["id"]

    def _get_or_create_subfolder_sync(self, service: Any, user_id: int, category: str) -> str:
        """Synchronously resolve the category subfolder for ``user_id``.

        Layout: ``{root}/user_{user_id}/{category folder}``. Both the per-user
        root and the category folder are looked up (created if missing) and then
        cached, so subsequent uploads for the same ``(user_id, category)`` pair
        skip the Drive list/create round trips entirely.
        """
        cache_key = (user_id, category)
        cached = self._folder_cache.get(cache_key)
        if cached is not None:
            return cached

        user_root_key = (user_id, _USER_ROOT_KEY)
        user_root_id = self._folder_cache.get(user_root_key)
        if user_root_id is None:
            user_root_id = self._get_or_create_folder_sync(
                service, f"user_{user_id}", self._root_folder_id
            )
            self._folder_cache[user_root_key] = user_root_id

        folder_name = _CATEGORY_FOLDERS.get(category, _CATEGORY_FOLDERS["other"])
        folder_id = self._get_or_create_folder_sync(service, folder_name, user_root_id)
        self._folder_cache[cache_key] = folder_id
        return folder_id

    async def get_or_create_folder(self, name: str, parent_id: str | None = None) -> str:
        """Return the folder ID for the given name, creating it if it doesn't exist."""
        service = await self._ensure_service()
        return await asyncio.to_thread(self._get_or_create_folder_sync, service, name, parent_id)

    def _upload_sync(
        self,
        service: Any,
        file_bytes: bytes,
        filename: str,
        category: str,
        user_id: int,
    ) -> DriveFile:
        """Synchronously upload bytes to the user's category subfolder on Drive."""
        folder_id = self._get_or_create_subfolder_sync(service, user_id, category)

        file_metadata = {"name": filename, "parents": [folder_id]}
        media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype="application/octet-stream")
        uploaded = (
            service.files()
            .create(body=file_metadata, media_body=media, fields="id, name, webViewLink")
            .execute()
        )
        return DriveFile(
            file_id=uploaded["id"],
            name=uploaded["name"],
            web_link=uploaded.get("webViewLink", ""),
        )

    async def upload_file(
        self,
        file_bytes: bytes,
        filename: str,
        category: str,
        user_id: int,
    ) -> DriveFile:
        """Upload ``file_bytes`` to the user's category subfolder and return metadata.

        Files are stored under ``{GOOGLE_DRIVE_FOLDER_ID}/user_{user_id}/{category}/``
        so each Telegram user gets an isolated folder tree on Drive.

        Raises DriveUploadError on any failure (OAuth, network, API errors).
        """
        service = await self._ensure_service()
        try:
            return await asyncio.to_thread(
                self._upload_sync, service, file_bytes, filename, category, user_id
            )
        except DriveUploadError:
            raise
        except Exception as exc:
            raise DriveUploadError(f"Drive upload failed: {exc}") from exc
