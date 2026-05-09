import uuid
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.item import Item, ItemType
from bot.repositories.item_repository import ItemRepository
from bot.services.drive_service import DriveFile, DriveService
from bot.services.media_service import MediaResult, MediaService
from bot.services.vision_service import MediaAnalysis, VisionService


def make_media_service(
    category: str = "photo",
    description: str = "A beautiful landscape",
    drive_link: str = "https://drive.google.com/file/d/abc",
) -> tuple[MediaService, MagicMock, MagicMock]:
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()

    mock_item = MagicMock(spec=Item)
    mock_item.id = uuid.uuid4()
    mock_item.type = ItemType.media
    mock_item.description = None

    repo = MagicMock(spec=ItemRepository)
    repo.create = AsyncMock(return_value=mock_item)

    vision = MagicMock(spec=VisionService)
    vision.analyze = AsyncMock(
        return_value=MediaAnalysis(category=category, description=description)
    )

    drive = MagicMock(spec=DriveService)
    drive.upload_file = AsyncMock(
        return_value=DriveFile(file_id="abc", name="photo.jpg", web_link=drive_link)
    )

    svc = MediaService(session=session, item_repo=repo, vision=vision, drive=drive)
    return svc, vision, drive


async def test_process_analyzes_and_uploads() -> None:
    svc, vision, drive = make_media_service()
    result = await svc.process(b"image bytes", "photo.jpg", user_id=1)

    vision.analyze.assert_awaited_once_with(b"image bytes", "image/jpeg", lang="en")
    drive.upload_file.assert_awaited_once_with(b"image bytes", "photo.jpg", "photo", 1)
    assert isinstance(result, MediaResult)
    assert result.analysis.category == "photo"
    assert result.drive_file.file_id == "abc"


async def test_process_forwards_lang_to_vision_service() -> None:
    """``lang`` passed to MediaService.process must reach VisionService.analyze."""
    svc, vision, _ = make_media_service()
    await svc.process(b"bytes", "img.jpg", user_id=1, lang="ru")

    vision.analyze.assert_awaited_once_with(b"bytes", "image/jpeg", lang="ru")


async def test_process_default_lang_is_english() -> None:
    """Omitting ``lang`` on process must still reach VisionService as 'en'."""
    svc, vision, _ = make_media_service()
    await svc.process(b"bytes", "img.jpg", user_id=1)

    vision.analyze.assert_awaited_once_with(b"bytes", "image/jpeg", lang="en")


async def test_process_saves_item_with_description() -> None:
    svc, _, _ = make_media_service(description="Landscape photo")
    result = await svc.process(b"bytes", "img.jpg", user_id=42)
    assert result.item.description == "Landscape photo"


async def test_process_commits_session() -> None:
    svc, _, _ = make_media_service()
    await svc.process(b"bytes", "img.jpg", user_id=1)
    svc._session.commit.assert_awaited_once()


def test_format_reply_contains_category_and_description() -> None:
    item = MagicMock(spec=Item)
    analysis = MediaAnalysis(category="receipt", description="Coffee shop receipt")
    drive_file = DriveFile(file_id="x", name="r.jpg", web_link="https://drive.google.com/x")
    result = MediaResult(item=item, analysis=analysis, drive_file=drive_file)

    reply = MediaService.format_reply(result)
    assert "📄" in reply
    assert "Receipt" in reply
    assert "Coffee shop receipt" in reply
    assert "drive.google.com" in reply


def test_format_reply_unknown_category_uses_box_emoji() -> None:
    item = MagicMock(spec=Item)
    analysis = MediaAnalysis(category="other", description="Unknown file")
    drive_file = DriveFile(file_id="x", name="f", web_link="https://drive.google.com")
    result = MediaResult(item=item, analysis=analysis, drive_file=drive_file)

    reply = MediaService.format_reply(result)
    assert "📦" in reply
