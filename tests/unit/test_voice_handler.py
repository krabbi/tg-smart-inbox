"""Unit tests for voice message handler."""

import io
import uuid as uuid_mod
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.fsm.context import FSMContext
from aiogram.types import Message, Voice

from bot.exceptions import TranscriptionError
from bot.handlers.voice import handle_voice
from bot.models.idea import IdeaComplexity, IdeaEffort
from bot.services.classifier import ClassifierService, MessageType
from bot.services.idea_service import IdeaService, SavedIdea
from bot.services.link_service import LinkService
from bot.services.note_service import NoteService, SavedNote
from bot.services.reminder_service import ReminderService
from bot.services.task_service import SavedTask, TaskService
from bot.services.time_parser import TimeParser
from bot.services.transcription_service import TranscriptionService
from bot.services.user_settings_service import UserSettingsService


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
    saved.idea.complexity = None
    saved.idea.effort = None
    idea_svc.save_idea = AsyncMock(return_value=saved)

    await handle_voice(
        msg,
        state=make_state(),
        transcription_service=svc,
        classifier=classifier,
        idea_service=idea_svc,
    )

    idea_svc.save_idea.assert_awaited_once_with("идея для приложения", 1, lang="en")
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
    call_args = mock_link.call_args[0]
    assert call_args[1] == "https://example.com"


async def test_handle_voice_downloads_audio_and_transcribes() -> None:
    msg = make_message()
    svc = MagicMock(spec=TranscriptionService)
    svc.transcribe = AsyncMock(return_value="test")

    await handle_voice(msg, state=make_state(), transcription_service=svc, classifier=None)

    svc.transcribe.assert_awaited_once_with(b"fake-audio")


async def test_handle_voice_idea_not_indexed_warns_user() -> None:
    """Voice idea without successful indexing surfaces the 'umny poisk' notification."""
    msg = make_message()
    svc = MagicMock(spec=TranscriptionService)
    svc.transcribe = AsyncMock(return_value="идея для приложения")

    classifier = MagicMock(spec=ClassifierService)
    classifier.classify = AsyncMock(return_value=MessageType.IDEA)

    idea_svc = MagicMock(spec=IdeaService)
    saved = MagicMock(spec=SavedIdea)
    saved.idea = MagicMock()
    saved.idea.tags = []
    saved.idea.complexity = None
    saved.idea.effort = None
    saved.indexed = False
    idea_svc.save_idea = AsyncMock(return_value=saved)

    await handle_voice(
        msg,
        state=make_state(),
        transcription_service=svc,
        classifier=classifier,
        idea_service=idea_svc,
        lang="ru",
    )

    replies = [c[0][0] for c in msg.answer.call_args_list]
    assert any("Умный поиск временно недоступен" in r for r in replies)


async def test_handle_voice_routes_idea_shows_complexity_labels() -> None:
    msg = make_message()
    svc = MagicMock(spec=TranscriptionService)
    svc.transcribe = AsyncMock(return_value="купить вертолёт")

    classifier = MagicMock(spec=ClassifierService)
    classifier.classify = AsyncMock(return_value=MessageType.IDEA)

    idea_svc = MagicMock(spec=IdeaService)
    saved = MagicMock(spec=SavedIdea)
    saved.idea = MagicMock()
    saved.idea.tags = []
    saved.idea.complexity = IdeaComplexity.complex
    saved.idea.effort = IdeaEffort.longterm
    idea_svc.save_idea = AsyncMock(return_value=saved)

    await handle_voice(
        msg,
        state=make_state(),
        transcription_service=svc,
        classifier=classifier,
        idea_service=idea_svc,
        lang="ru",
    )

    replies = [c[0][0] for c in msg.answer.call_args_list]
    assert any("сложная" in r for r in replies)
    assert any("долгосрочно" in r for r in replies)


async def test_handle_voice_routes_task_without_time_shows_remind_button() -> None:
    """Voice task without time expression shows inline Remind button."""
    msg = make_message()
    svc = MagicMock(spec=TranscriptionService)
    svc.transcribe = AsyncMock(return_value="купить молоко")

    classifier = MagicMock(spec=ClassifierService)
    classifier.classify = AsyncMock(return_value=MessageType.TASK)

    mock_item = MagicMock()
    mock_item.id = "task-uuid"
    task_svc = MagicMock(spec=TaskService)
    task_svc.save = AsyncMock(return_value=SavedTask(item=mock_item, indexed=True))

    await handle_voice(
        msg,
        state=make_state(),
        transcription_service=svc,
        classifier=classifier,
        task_service=task_svc,
        lang="ru",
    )

    task_svc.save.assert_awaited_once_with("купить молоко", 1)
    # The last answer call should have "Задача сохранена" with a remind button
    last_call = msg.answer.call_args_list[-1]
    assert "Задача сохранена" in last_call[0][0]
    kb = last_call[1]["reply_markup"]
    assert kb is not None
    assert "task_remind:task-uuid" in kb.inline_keyboard[0][0].callback_data


async def test_handle_voice_routes_task_with_time_auto_creates_reminder() -> None:
    """Voice task with time expression auto-parses time and creates reminder."""
    msg = make_message()
    svc = MagicMock(spec=TranscriptionService)
    svc.transcribe = AsyncMock(return_value="завтра сдать отчёт")

    classifier = MagicMock(spec=ClassifierService)
    classifier.classify = AsyncMock(return_value=MessageType.TASK)

    item_id = uuid_mod.uuid4()
    mock_item = MagicMock()
    mock_item.id = item_id
    task_svc = MagicMock(spec=TaskService)
    task_svc.save = AsyncMock(return_value=SavedTask(item=mock_item, indexed=True))

    remind_at = datetime(2026, 4, 12, 10, 0, tzinfo=UTC)
    time_parser = MagicMock(spec=TimeParser)
    time_parser.parse = AsyncMock(return_value=remind_at)

    reminder_svc = MagicMock(spec=ReminderService)
    reminder_svc.create = AsyncMock()

    state = make_state()

    with patch("bot.handlers.voice.has_time_expression", return_value=True):
        await handle_voice(
            msg,
            state=state,
            transcription_service=svc,
            classifier=classifier,
            task_service=task_svc,
            time_parser=time_parser,
            reminder_service=reminder_svc,
        )

    task_svc.save.assert_awaited_once_with("завтра сдать отчёт", 1)
    reminder_svc.create.assert_awaited_once_with(item_id=item_id, remind_at=remind_at)
    # FSM should NOT be entered
    state.set_state.assert_not_awaited()
    # Confirmation should contain bell emoji
    replies = [c[0][0] for c in msg.answer.call_args_list]
    assert any("\U0001f514" in r for r in replies)


async def test_handle_voice_task_with_time_forwards_user_timezone_to_parser() -> None:
    """Voice task with time uses UserSettingsService.get_timezone() and forwards it to TimeParser.parse."""
    msg = make_message(user_id=42)
    svc = MagicMock(spec=TranscriptionService)
    svc.transcribe = AsyncMock(return_value="завтра сдать отчёт")

    classifier = MagicMock(spec=ClassifierService)
    classifier.classify = AsyncMock(return_value=MessageType.TASK)

    item_id = uuid_mod.uuid4()
    mock_item = MagicMock()
    mock_item.id = item_id
    task_svc = MagicMock(spec=TaskService)
    task_svc.save = AsyncMock(return_value=SavedTask(item=mock_item, indexed=True))

    remind_at = datetime(2026, 4, 12, 7, 0, tzinfo=UTC)
    time_parser = MagicMock(spec=TimeParser)
    time_parser.parse = AsyncMock(return_value=remind_at)

    reminder_svc = MagicMock(spec=ReminderService)
    reminder_svc.create = AsyncMock()

    settings_svc = MagicMock(spec=UserSettingsService)
    settings_svc.get_timezone = AsyncMock(return_value="Europe/Moscow")

    with patch("bot.handlers.voice.has_time_expression", return_value=True):
        await handle_voice(
            msg,
            state=make_state(),
            transcription_service=svc,
            classifier=classifier,
            task_service=task_svc,
            time_parser=time_parser,
            reminder_service=reminder_svc,
            user_settings_service=settings_svc,
        )

    settings_svc.get_timezone.assert_awaited_once_with(42)
    time_parser.parse.assert_awaited_once()
    assert time_parser.parse.call_args.kwargs["user_tz"] == "Europe/Moscow"
    reminder_svc.create.assert_awaited_once_with(item_id=item_id, remind_at=remind_at)


async def test_handle_voice_routes_note_and_confirms() -> None:
    msg = make_message()
    svc = MagicMock(spec=TranscriptionService)
    svc.transcribe = AsyncMock(return_value="Байкал — самое глубокое озеро")

    classifier = MagicMock(spec=ClassifierService)
    classifier.classify = AsyncMock(return_value=MessageType.NOTE)

    mock_item = MagicMock()
    note_svc = MagicMock(spec=NoteService)
    note_svc.save = AsyncMock(return_value=SavedNote(item=mock_item, indexed=True))

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
