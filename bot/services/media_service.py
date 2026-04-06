from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

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
    ) -> MediaResult:
        """Analyze, upload, save, and return MediaResult.

        Raises VisionService fallback errors or DriveUploadError on failure.
        """
        analysis = await self._vision.analyze(file_bytes, media_type)
        drive_file = self._drive.upload(file_bytes, filename, analysis.category)
        item = await self._repo.create(
            user_id=user_id,
            type=ItemType.media,
            content=drive_file.web_link,
        )
        item.description = analysis.description
        await self._session.commit()
        return MediaResult(item=item, analysis=analysis, drive_file=drive_file)

    @staticmethod
    def format_reply(result: MediaResult) -> str:
        """Format the bot reply message for a processed media file."""
        emoji = _CATEGORY_EMOJI.get(result.analysis.category, "📦")
        return (
            f"{emoji} <b>{result.analysis.category.capitalize()}</b>\n\n"
            f"{result.analysis.description}\n\n"
            f'<a href="{result.drive_file.web_link}">Открыть в Drive</a>'
        )
