"""Unit tests for voice message handler."""

import io
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.fsm.context import FSMContext
from aiogram.types import Message, Voice

from bot.exceptions import TranscriptionError
from bot.handlers.voice import handle_voice
from bot.services.classifier import ClassifierService, MessageType
from bot.services.idea_service import IdeaService, SavedIdea
from bot.services.link_service import LinkService
from bot.services.note_service import NoteService, SavedNote
from bot.services.task_service import SavedTask, TaskService
from bot.services.transcription_service import TranscriptionService


def make_state() -> FSMContext:
    state = MagicMock(spec=FSMContext)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    return state


def make_message(voice_file_id: str = "voice-file-id", user_id: int = 1) -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock()
    msg.forward_origin = None

    user = MagicMock()
    user.id = user_id
    msg.from_user = user

    voice = MagicMock(spec=Voice)
    voice.file_id = voice_file_id
    msg.voice = voice

    bot = MagicMock()
    file = MagicMock()
    file.file_path = "voice/file.oga"
    bot.get_file = AsyncMock(return_value=file)
    bot.download_file = AsyncMock(return_value=io.BytesIO(b"fake-audio"))
    msg.bot = bot

    return msg


async def test_handle_voice_no_service_replies_setup_instructions() -> None:
    msg = make_message()
    await handle_voice(msg, state=make_state(), transcription_service=None)
    msg.answer.assert_awaited_once()
    assert "GROQ_API_KEY" in msg.answer.call_args[0][0]


async def test_handle_voice_transcription_error_shows_error_message() -> None:
    msg = make_message()
    svc = MagicMock(spec=TranscriptionService)
    svc.transcribe = AsyncMock(side_effect=TranscriptionError("Неверный GROQ_API_KEY."))

    await handle_voice(msg, state=make_state(), transcription_service=svc)
    msg.answer.assert_awaited_once()
    assert "GROQ_API_KEY" in msg.answer.call_args[0][0]


async def test_handle_voice_shows_transcript() -> None:
    msg = make_message()
    svc = MagicMock(spec=TranscriptionService)
    svc.transcribe = AsyncMock(return_value="купить молоко")

    await handle_voice(msg, state=make_state(), transcription_service=svc, classifier=None)

    first_reply = msg.answer.call_args_list[0][0][0]
    assert "купить молоко" in first_reply
    assert "🎤" in first_reply


async def test_handle_voice_routes_idea_to_idea_service() -> None:
    msg = make_message()
    svc = MagicMock(spec=TranscriptionService)
    svc.transcribe = AsyncMock(return_value="идея для приложения")

    classifier = MagicMock(spec=ClassifierService)
    classifier.classify = AsyncMock(return_value=MessageType.IDEA)

    idea_svc = MagicMock(spec=IdeaService)
    saved = MagicMock(spec=SavedIdea)
    saved.idea = MagicMock()
    saved.idea.tags = ["tech"]
    idea_svc.save_idea = AsyncMock(return_value=saved)

    await handle_voice(
        msg,
        state=make_state(),
        transcription_service=svc,
        classifier=classifier,
        idea_service=idea_svc,
    )

    idea_svc.save_idea.assert_awaited_once_with("идея для приложения", 1)
    replies = [c[0][0] for c in msg.answer.call_args_list]
    assert any("💡" in r for r in replies)


async def test_handle_voice_routes_link_to_link_handler() -> None:
    msg = make_message()
    svc = MagicMock(spec=TranscriptionService)
    svc.transcribe = AsyncMock(return_value="смотри https://example.com")

    classifier = MagicMock(spec=ClassifierService)
    classifier.classify = AsyncMock(return_value=MessageType.LINK)

    link_svc = MagicMock(spec=LinkService)

    with patch("bot.handlers.voice.handle_link_message", new=AsyncMock()) as mock_link:
        await handle_voice(
            msg,
            state=make_state(),
            transcription_service=svc,
            classifier=classifier,
            link_service=link_svc,
        )

    mock_link.assert_awaited_once()
    _, called_url, _ = mock_link.call_args[0]
    assert called_url == "https://example.com"


async def test_handle_voice_downloads_audio_and_transcribes() -> None:
    msg = make_message()
    svc = MagicMock(spec=TranscriptionService)
    svc.transcribe = AsyncMock(return_value="test")

    await handle_voice(msg, state=make_state(), transcription_service=svc, classifier=None)

    svc.transcribe.assert_awaited_once_with(b"fake-audio")


async def test_handle_voice_routes_task_and_asks_reminder() -> None:
    msg = make_message()
    svc = MagicMock(spec=TranscriptionService)
    svc.transcribe = AsyncMock(return_value="купить молоко")

    classifier = MagicMock(spec=ClassifierService)
    classifier.classify = AsyncMock(return_value=MessageType.TASK)

    mock_item = MagicMock()
    mock_item.id = "task-uuid"
    task_svc = MagicMock(spec=TaskService)
    task_svc.save = AsyncMock(return_value=SavedTask(item=mock_item))

    with patch("bot.handlers.voice.ask_reminder", new=AsyncMock()) as mock_ask:
        await handle_voice(
            msg,
            state=make_state(),
            transcription_service=svc,
            classifier=classifier,
            task_service=task_svc,
        )

    task_svc.save.assert_awaited_once_with("купить молоко", 1)
    mock_ask.assert_awaited_once()
    assert mock_ask.call_args[1]["item_id"] == "task-uuid"


async def test_handle_voice_routes_note_and_confirms() -> None:
    msg = make_message()
    svc = MagicMock(spec=TranscriptionService)
    svc.transcribe = AsyncMock(return_value="Байкал — самое глубокое озеро")

    classifier = MagicMock(spec=ClassifierService)
    classifier.classify = AsyncMock(return_value=MessageType.NOTE)

    mock_item = MagicMock()
    note_svc = MagicMock(spec=NoteService)
    note_svc.save = AsyncMock(return_value=SavedNote(item=mock_item))

    await handle_voice(
        msg,
        state=make_state(),
        transcription_service=svc,
        classifier=classifier,
        note_service=note_svc,
    )

    note_svc.save.assert_awaited_once_with("Байкал — самое глубокое озеро", 1)
    replies = [c[0][0] for c in msg.answer.call_args_list]
    assert any("📝" in r for r in replies)
