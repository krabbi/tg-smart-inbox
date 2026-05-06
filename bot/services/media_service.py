from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from bot.i18n import DEFAULT_LANGUAGE, t
from bot.models.item import Item, ItemType
from bot.repositories.item_repository import ItemRepository
from bot.services.drive_service import DriveFile, DriveService
from bot.services.vision_service import MediaAnalysis, VisionService

_CATEGORY_EMOJI = {
    "receipt": "📄",
    "document": "📁",
    "screenshot": "🖥️",
    "photo": "🖼️",
    "meme": "😄",
    "other": "📦",
}

_CATEGORY_KEY = {
    "receipt": "media_category_receipt",
    "document": "media_category_document",
    "screenshot": "media_category_screenshot",
    "photo": "media_category_photo",
    "meme": "media_category_meme",
    "other": "media_category_other",
}


@dataclass(frozen=True)
class MediaResult:
    """Result of processing a media file."""

    item: Item
    analysis: MediaAnalysis
    drive_file: DriveFile


class MediaService:
    """Orchestrate media analysis, Drive upload, and DB persistence."""

    def __init__(
        self,
        session: AsyncSession,
        item_repo: ItemRepository,
        vision: VisionService,
        drive: DriveService,
    ) -> None:
        self._session = session
        self._repo = item_repo
        self._vision = vision
        self._drive = drive

    async def process(
        self,
        file_bytes: bytes,
        filename: str,
        user_id: int,
        media_type: str = "image/jpeg",
        lang: str = DEFAULT_LANGUAGE,
    ) -> MediaResult:
        """Analyze, upload, save, and return MediaResult.

        ``lang`` is forwarded to :class:`VisionService` so the image description
        is produced in the user's interface language.

        Raises VisionService fallback errors or DriveUploadError on failure.
        """
        analysis = await self._vision.analyze(file_bytes, media_type, lang=lang)
        drive_file = await self._drive.upload(file_bytes, filename, analysis.category)
        item = await self._repo.create(
            user_id=user_id,
            type=ItemType.media,
            content=drive_file.web_link,
        )
        item.description = analysis.description
        await self._session.commit()
        return MediaResult(item=item, analysis=analysis, drive_file=drive_file)

    @staticmethod
    def format_reply(result: MediaResult, lang: str = "en") -> str:
        """Format the bot reply message for a processed media file."""
        emoji = _CATEGORY_EMOJI.get(result.analysis.category, "📦")
        category_label = t(
            _CATEGORY_KEY.get(result.analysis.category, "media_category_other"), lang
        )
        open_label = t("media_open_in_drive", lang)
        return (
            f"{emoji} <b>{category_label}</b>\n\n"
            f"{result.analysis.description}\n\n"
            f'<a href="{result.drive_file.web_link}">{open_label}</a>'
        )
