import io
import logging
import os
from dataclasses import dataclass
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
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


@dataclass(frozen=True)
class DriveFile:
    """Metadata for an uploaded Drive file."""

    file_id: str
    name: str
    web_link: str


class DriveService:
    """Upload files to Google Drive and manage category subfolders."""

    def __init__(self, config: Config) -> None:
        self._root_folder_id = config.google_drive_folder_id
        self._credentials_file = config.google_drive_credentials_file
        self._token_file = config.google_drive_token_file
        self._service = self._build_service()

    def _load_credentials(self) -> Credentials:
        """Load OAuth user credentials, refreshing or running the auth flow as needed.

        On first run (no token file): runs the InstalledAppFlow to obtain credentials,
        which requires a browser-based user consent. The resulting token (with refresh
        token) is persisted to ``google_drive_token_file`` for reuse.

        On subsequent runs: loads the token from disk and refreshes it automatically
        when expired, using the stored refresh token.
        """
        creds: Credentials | None = None
        if os.path.exists(self._token_file):
            creds = Credentials.from_authorized_user_file(self._token_file, _SCOPES)

        if creds is None or not creds.valid:
            if creds is not None and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(self._credentials_file, _SCOPES)
                creds = flow.run_local_server(port=0)
            with open(self._token_file, "w", encoding="utf-8") as token_fp:
                token_fp.write(creds.to_json())

        return creds

    def _build_service(self) -> Any:
        """Build an authenticated Google Drive API service."""
        credentials = self._load_credentials()
        return build("drive", "v3", credentials=credentials, cache_discovery=False)

    def get_or_create_folder(self, name: str, parent_id: str | None = None) -> str:
        """Return the folder ID for the given name, creating it if it doesn't exist."""
        parent = parent_id or self._root_folder_id
        # Escape single quotes per Drive API query syntax
        escaped_name = name.replace("'", "\\'")
        query = (
            f"name='{escaped_name}' and mimeType='application/vnd.google-apps.folder'"
            f" and '{parent}' in parents and trashed=false"
        )
        results = (
            self._service.files().list(q=query, fields="files(id, name)", spaces="drive").execute()
        )
        files = results.get("files", [])
        if files:
            return files[0]["id"]

        folder_metadata = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent],
        }
        folder = self._service.files().create(body=folder_metadata, fields="id").execute()
        return folder["id"]

    def upload(self, file_bytes: bytes, filename: str, category: str) -> DriveFile:
        """Upload file_bytes to the category subfolder and return DriveFile metadata.

        Raises DriveUploadError on any failure.
        """
        try:
            folder_name = _CATEGORY_FOLDERS.get(category, _CATEGORY_FOLDERS["other"])
            folder_id = self.get_or_create_folder(folder_name)

            file_metadata = {"name": filename, "parents": [folder_id]}
            media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype="application/octet-stream")
            uploaded = (
                self._service.files()
                .create(body=file_metadata, media_body=media, fields="id, name, webViewLink")
                .execute()
            )
            return DriveFile(
                file_id=uploaded["id"],
                name=uploaded["name"],
                web_link=uploaded.get("webViewLink", ""),
            )
        except Exception as exc:
            raise DriveUploadError(f"Drive upload failed: {exc}") from exc
