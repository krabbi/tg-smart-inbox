import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.fsm.context import FSMContext
from aiogram.types import Message, User

from bot.exceptions import TimeParseError
from bot.handlers.messages import _handle_task_with_time, _is_suggestion_query, handle_text
from bot.models.idea import IdeaComplexity, IdeaEffort
from bot.services.classifier import ClassifierService, MessageType
from bot.services.idea_service import IdeaService, SavedIdea
from bot.services.link_service import LinkService
from bot.services.note_service import NoteService, SavedNote
from bot.services.reminder_service import ReminderService
from bot.services.task_service import SavedTask, TaskService
from bot.services.time_parser import TimeParser
from bot.services.user_settings_service import UserSettingsService
from bot.utils.text import extract_url as _extract_url
from bot.utils.text import has_time_expression as _has_time_expression


def make_message(text: str, user_id: int = 1, forwarded: bool = False) -> Message:
    user = MagicMock(spec=User)
    user.id = user_id
    msg = MagicMock(spec=Message)
    msg.from_user = user
    msg.text = text
    msg.forward_origin = MagicMock() if forwarded else None
    msg.answer = AsyncMock()
    return msg


def make_state() -> FSMContext:
    state = MagicMock(spec=FSMContext)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    state.get_state = AsyncMock(return_value=None)
    return state


def make_classifier(msg_type: MessageType) -> ClassifierService:
    svc = MagicMock(spec=ClassifierService)
    svc.classify = AsyncMock(return_value=msg_type)
    return svc


# ── _extract_url helper ───────────────────────────────────────────────────────


def test_extract_url_finds_https() -> None:
    assert _extract_url("Check https://example.com") == "https://example.com"


def test_extract_url_returns_none_for_plain_text() -> None:
    assert _extract_url("no url here") is None


def test_extract_url_finds_first_url() -> None:
    result = _extract_url("https://first.com and https://second.com")
    assert result == "https://first.com"


# ── has_time_expression helper ────────────────────────────────────────────────


def test_has_time_expression_tomorrow() -> None:
    assert _has_time_expression("завтра сдать отчёт")


def test_has_time_expression_at_time() -> None:
    assert _has_time_expression("встреча в 14:00")


def test_has_time_expression_interval() -> None:
    assert _has_time_expression("через 2 часа позвонить")


def test_has_time_expression_weekday() -> None:
    assert _has_time_expression("в пятницу презентация")


def test_has_time_expression_english() -> None:
    assert _has_time_expression("call Tom tomorrow")
    assert _has_time_expression("meeting at 10")


def test_has_time_expression_no_match() -> None:
    assert not _has_time_expression("купить молоко")
    assert not _has_time_expression("позвонить Маше")
    assert not _has_time_expression("вчера забыл позвонить")  # past — no future intent


# ── handle_text with no classifier ───────────────────────────────────────────


async def test_handle_text_no_classifier_gives_stub_reply() -> None:
    msg = make_message("hello")
    await handle_text(msg, state=make_state(), classifier=None)
    msg.answer.assert_awaited_once()


# ── handle_text with classifier ──────────────────────────────────────────────


async def test_handle_text_link_calls_link_handler() -> None:
    msg = make_message("https://example.com")
    classifier = make_classifier(MessageType.LINK)
    link_service = MagicMock(spec=LinkService)

    with patch("bot.handlers.messages.handle_link_message", new=AsyncMock()) as mock_handle:
        await handle_text(msg, state=make_state(), classifier=classifier, link_service=link_service)
        mock_handle.assert_awaited_once()


async def test_handle_text_task_without_time_shows_remind_button() -> None:
    """Task without time expression saves and shows inline Remind button (no dialog)."""
    msg = make_message("купить молоко")
    classifier = make_classifier(MessageType.TASK)
    state = make_state()

    mock_item = MagicMock()
    mock_item.id = "item-uuid"
    task_svc = MagicMock(spec=TaskService)
    task_svc.save = AsyncMock(return_value=SavedTask(item=mock_item))

    await handle_text(msg, state=state, classifier=classifier, task_service=task_svc, lang="ru")

    # Should NOT enter FSM
    state.set_state.assert_not_awaited()
    # Should show confirmation with remind button
    msg.answer.assert_awaited_once()
    call_args = msg.answer.call_args
    assert "Задача сохранена" in call_args[0][0]
    kb = call_args[1]["reply_markup"]
    assert kb is not None
    assert "task_remind:item-uuid" in kb.inline_keyboard[0][0].callback_data


async def test_handle_text_task_with_time_auto_creates_reminder() -> None:
    """Task with time expression auto-parses time and creates reminder without FSM."""
    msg = make_message("завтра сдать отчёт")
    classifier = make_classifier(MessageType.TASK)
    state = make_state()

    mock_item = MagicMock()
    mock_item.id = uuid.uuid4()
    task_svc = MagicMock(spec=TaskService)
    task_svc.save = AsyncMock(return_value=SavedTask(item=mock_item))

    remind_at = datetime(2026, 6, 2, 9, 0, tzinfo=UTC)
    time_parser = MagicMock(spec=TimeParser)
    time_parser.parse = AsyncMock(return_value=remind_at)

    reminder_svc = MagicMock(spec=ReminderService)
    reminder_svc.create = AsyncMock()

    await handle_text(
        msg,
        state=state,
        classifier=classifier,
        task_service=task_svc,
        time_parser=time_parser,
        reminder_service=reminder_svc,
        lang="ru",
    )

    # Should auto-create reminder
    reminder_svc.create.assert_awaited_once()
    # Should NOT enter FSM
    state.set_state.assert_not_awaited()
    # Should confirm with bell emoji
    reply = msg.answer.call_args[0][0]
    assert "Задача сохранена" in reply
    assert "\U0001f514" in reply


async def test_handle_text_task_with_time_forwards_user_timezone_to_parser() -> None:
    """Task with time uses UserSettingsService.get_timezone() and forwards it to TimeParser.parse."""
    msg = make_message("завтра сдать отчёт", user_id=42)
    classifier = make_classifier(MessageType.TASK)
    state = make_state()

    mock_item = MagicMock()
    mock_item.id = uuid.uuid4()
    task_svc = MagicMock(spec=TaskService)
    task_svc.save = AsyncMock(return_value=SavedTask(item=mock_item))

    remind_at = datetime(2026, 6, 2, 7, 0, tzinfo=UTC)
    time_parser = MagicMock(spec=TimeParser)
    time_parser.parse = AsyncMock(return_value=remind_at)

    reminder_svc = MagicMock(spec=ReminderService)
    reminder_svc.create = AsyncMock()

    settings_svc = MagicMock(spec=UserSettingsService)
    settings_svc.get_timezone = AsyncMock(return_value="Europe/Moscow")

    await handle_text(
        msg,
        state=state,
        classifier=classifier,
        task_service=task_svc,
        time_parser=time_parser,
        reminder_service=reminder_svc,
        user_settings_service=settings_svc,
    )

    settings_svc.get_timezone.assert_awaited_once_with(42)
    time_parser.parse.assert_awaited_once()
    assert time_parser.parse.call_args.kwargs["user_tz"] == "Europe/Moscow"
    reminder_svc.create.assert_awaited_once()


async def test_handle_text_task_with_time_parse_error_enters_fsm() -> None:
    """Task with time expression that fails parsing enters FSM for manual input."""
    msg = make_message("завтра сдать отчёт")
    classifier = make_classifier(MessageType.TASK)
    state = make_state()

    mock_item = MagicMock()
    mock_item.id = uuid.uuid4()
    task_svc = MagicMock(spec=TaskService)
    task_svc.save = AsyncMock(return_value=SavedTask(item=mock_item))

    time_parser = MagicMock(spec=TimeParser)
    time_parser.parse = AsyncMock(side_effect=TimeParseError("unparseable"))

    reminder_svc = MagicMock(spec=ReminderService)

    await handle_text(
        msg,
        state=state,
        classifier=classifier,
        task_service=task_svc,
        time_parser=time_parser,
        reminder_service=reminder_svc,
        lang="ru",
    )

    from bot.handlers.reminders import ReminderStates

    state.set_state.assert_awaited_once_with(ReminderStates.waiting_for_time)
    msg.answer.assert_awaited_once()
    assert "Уточни время" in msg.answer.call_args[0][0]


async def test_handle_text_task_with_time_no_services_shows_button() -> None:
    """Task with time but no time_parser/reminder_service shows remind button."""
    msg = make_message("завтра сдать отчёт")
    classifier = make_classifier(MessageType.TASK)
    state = make_state()

    mock_item = MagicMock()
    mock_item.id = "item-uuid"
    task_svc = MagicMock(spec=TaskService)
    task_svc.save = AsyncMock(return_value=SavedTask(item=mock_item))

    await handle_text(
        msg,
        state=state,
        classifier=classifier,
        task_service=task_svc,
        time_parser=None,
        reminder_service=None,
        lang="ru",
    )

    msg.answer.assert_awaited_once()
    assert "Задача сохранена" in msg.answer.call_args[0][0]
    kb = msg.answer.call_args[1]["reply_markup"]
    assert kb is not None


async def test_handle_text_task_with_time_reminder_create_error_shows_button() -> None:
    """When auto-creating reminder fails, show task saved + remind button."""
    msg = make_message("завтра сдать отчёт")
    classifier = make_classifier(MessageType.TASK)
    state = make_state()

    mock_item = MagicMock()
    mock_item.id = uuid.uuid4()
    task_svc = MagicMock(spec=TaskService)
    task_svc.save = AsyncMock(return_value=SavedTask(item=mock_item))

    remind_at = datetime(2026, 6, 2, 9, 0, tzinfo=UTC)
    time_parser = MagicMock(spec=TimeParser)
    time_parser.parse = AsyncMock(return_value=remind_at)

    reminder_svc = MagicMock(spec=ReminderService)
    reminder_svc.create = AsyncMock(side_effect=Exception("DB error"))

    await handle_text(
        msg,
        state=state,
        classifier=classifier,
        task_service=task_svc,
        time_parser=time_parser,
        reminder_service=reminder_svc,
        lang="ru",
    )

    reply = msg.answer.call_args[0][0]
    assert "не удалось создать напоминание" in reply.lower()
    kb = msg.answer.call_args[1]["reply_markup"]
    assert kb is not None


async def test_handle_text_task_save_error_sends_error_reply() -> None:
    msg = make_message("купить молоко")
    classifier = make_classifier(MessageType.TASK)
    task_svc = MagicMock(spec=TaskService)
    task_svc.save = AsyncMock(side_effect=Exception("DB error"))

    await handle_text(
        msg, state=make_state(), classifier=classifier, task_service=task_svc, lang="ru"
    )
    assert "Не удалось" in msg.answer.call_args[0][0]


async def test_handle_text_task_no_service_gives_stub() -> None:
    msg = make_message("купить молоко")
    classifier = make_classifier(MessageType.TASK)
    await handle_text(msg, state=make_state(), classifier=classifier, task_service=None)
    msg.answer.assert_awaited_once()


async def test_handle_text_note_saves_and_confirms() -> None:
    msg = make_message("Байкал — самое глубокое озеро")
    classifier = make_classifier(MessageType.NOTE)

    mock_item = MagicMock()
    note_svc = MagicMock(spec=NoteService)
    note_svc.save = AsyncMock(return_value=SavedNote(item=mock_item))

    await handle_text(msg, state=make_state(), classifier=classifier, note_service=note_svc)
    note_svc.save.assert_awaited_once()
    assert "📝" in msg.answer.call_args[0][0]


async def test_handle_text_note_save_error_sends_error_reply() -> None:
    msg = make_message("Байкал — самое глубокое озеро")
    classifier = make_classifier(MessageType.NOTE)
    note_svc = MagicMock(spec=NoteService)
    note_svc.save = AsyncMock(side_effect=Exception("DB error"))

    await handle_text(
        msg, state=make_state(), classifier=classifier, note_service=note_svc, lang="ru"
    )
    assert "Не удалось" in msg.answer.call_args[0][0]


async def test_handle_text_note_no_service_gives_stub() -> None:
    msg = make_message("Байкал — самое глубокое озеро")
    classifier = make_classifier(MessageType.NOTE)
    await handle_text(msg, state=make_state(), classifier=classifier, note_service=None)
    msg.answer.assert_awaited_once()


async def test_handle_text_idea_saves_and_shows_tags() -> None:
    msg = make_message("хочу сделать приложение")
    classifier = make_classifier(MessageType.IDEA)

    idea_svc = MagicMock(spec=IdeaService)
    mock_idea = MagicMock()
    mock_idea.tags = ["app", "mobile"]
    mock_idea.complexity = None
    mock_idea.effort = None
    idea_svc.save_idea = AsyncMock(return_value=MagicMock(spec=SavedIdea, idea=mock_idea))

    await handle_text(msg, state=make_state(), classifier=classifier, idea_service=idea_svc)
    msg.answer.assert_awaited_once()
    reply = msg.answer.call_args[0][0]
    assert "💡" in reply
    assert "#app" in reply


async def test_handle_text_idea_shows_complexity_labels() -> None:
    msg = make_message("купить вертолёт")
    classifier = make_classifier(MessageType.IDEA)

    idea_svc = MagicMock(spec=IdeaService)
    mock_idea = MagicMock()
    mock_idea.tags = []
    mock_idea.complexity = IdeaComplexity.complex
    mock_idea.effort = IdeaEffort.longterm
    idea_svc.save_idea = AsyncMock(return_value=MagicMock(spec=SavedIdea, idea=mock_idea))

    await handle_text(
        msg, state=make_state(), classifier=classifier, idea_service=idea_svc, lang="ru"
    )
    reply = msg.answer.call_args[0][0]
    assert "сложная" in reply
    assert "долгосрочно" in reply


async def test_handle_text_idea_no_service_gives_stub() -> None:
    msg = make_message("хочу сделать приложение")
    classifier = make_classifier(MessageType.IDEA)
    await handle_text(msg, state=make_state(), classifier=classifier, idea_service=None)
    msg.answer.assert_awaited_once()


async def test_handle_text_idea_save_error_sends_error_reply() -> None:
    msg = make_message("хочу сделать приложение")
    classifier = make_classifier(MessageType.IDEA)
    idea_svc = MagicMock(spec=IdeaService)
    idea_svc.save_idea = AsyncMock(side_effect=Exception("DB error"))

    await handle_text(
        msg, state=make_state(), classifier=classifier, idea_service=idea_svc, lang="ru"
    )
    msg.answer.assert_awaited_once()
    assert "Не удалось" in msg.answer.call_args[0][0]


async def test_handle_text_idea_not_indexed_warns_user() -> None:
    """When embedding fails, the handler tells the user smart search is temporarily down."""
    msg = make_message("хочу сделать приложение")
    classifier = make_classifier(MessageType.IDEA)

    idea_svc = MagicMock(spec=IdeaService)
    mock_idea = MagicMock()
    mock_idea.tags = []
    mock_idea.complexity = None
    mock_idea.effort = None
    saved = MagicMock(spec=SavedIdea)
    saved.idea = mock_idea
    saved.indexed = False
    idea_svc.save_idea = AsyncMock(return_value=saved)

    await handle_text(
        msg, state=make_state(), classifier=classifier, idea_service=idea_svc, lang="ru"
    )

    replies = [c[0][0] for c in msg.answer.call_args_list]
    assert any("Идея сохранена" in r for r in replies)
    assert any("Умный поиск временно недоступен" in r for r in replies)


# ── suggestion query detection ────────────────────────────────────────────────


def test_is_suggestion_query_russian_variants() -> None:
    assert _is_suggestion_query("что поделать?")
    assert _is_suggestion_query("чем заняться сегодня?")
    assert _is_suggestion_query("куда порекомендуешь?")


def test_is_suggestion_query_english() -> None:
    assert _is_suggestion_query("give me an idea")
    assert _is_suggestion_query("what should I do today?")
    assert _is_suggestion_query("suggest something interesting")


def test_is_suggestion_query_negative() -> None:
    assert not _is_suggestion_query("хочу сделать приложение")
    assert not _is_suggestion_query("купить молоко")
    assert not _is_suggestion_query("https://example.com")


async def test_handle_text_suggestion_query_calls_suggest() -> None:
    msg = make_message("чем заняться?")
    classifier = make_classifier(MessageType.NOTE)
    idea_svc = MagicMock(spec=IdeaService)
    idea_svc.suggest = AsyncMock(return_value="Вот что можно сделать: ...")

    await handle_text(msg, state=make_state(), classifier=classifier, idea_service=idea_svc)
    idea_svc.suggest.assert_awaited_once()
    # classifier should NOT be called — fast path
    classifier.classify.assert_not_awaited()


async def test_handle_text_link_without_link_service_gives_stub() -> None:
    msg = make_message("https://example.com")
    classifier = make_classifier(MessageType.LINK)
    await handle_text(msg, state=make_state(), classifier=classifier, link_service=None)
    msg.answer.assert_awaited_once()


# ── _handle_task_with_time unit tests ─────────────────────────────────────────


async def test_handle_task_with_time_auto_creates_reminder() -> None:
    """Direct test of _handle_task_with_time — successful auto-parse."""
    msg = make_message("завтра в 10")
    state = make_state()
    item_id = str(uuid.uuid4())

    remind_at = datetime(2026, 6, 2, 10, 0, tzinfo=UTC)
    tp = MagicMock(spec=TimeParser)
    tp.parse = AsyncMock(return_value=remind_at)
    rs = MagicMock(spec=ReminderService)
    rs.create = AsyncMock()

    await _handle_task_with_time(msg, "завтра в 10", item_id, state, tp, rs, lang="ru")

    rs.create.assert_awaited_once()
    state.set_state.assert_not_awaited()
    assert "\U0001f514" in msg.answer.call_args[0][0]


async def test_handle_task_with_time_parse_error_enters_fsm() -> None:
    """Direct test of _handle_task_with_time — parse error falls back to FSM."""
    msg = make_message("завтра")
    state = make_state()
    item_id = str(uuid.uuid4())

    tp = MagicMock(spec=TimeParser)
    tp.parse = AsyncMock(side_effect=TimeParseError("fail"))
    rs = MagicMock(spec=ReminderService)

    await _handle_task_with_time(msg, "завтра", item_id, state, tp, rs, lang="ru")

    from bot.handlers.reminders import ReminderStates

    state.set_state.assert_awaited_once_with(ReminderStates.waiting_for_time)


async def test_handle_task_with_time_no_services_shows_button() -> None:
    """When time_parser or reminder_service is None, show remind button."""
    msg = make_message("завтра")
    state = make_state()
    item_id = "some-id"

    await _handle_task_with_time(msg, "завтра", item_id, state, None, None, lang="ru")

    msg.answer.assert_awaited_once()
    assert "Задача сохранена" in msg.answer.call_args[0][0]
    kb = msg.answer.call_args[1]["reply_markup"]
    assert kb is not None


# ── multiple tasks without blocking (AC 3 consequence) ───────────────────────


async def test_multiple_tasks_without_time_no_fsm_blocking() -> None:
    """Multiple tasks without time can be sent without FSM blocking."""
    classifier = make_classifier(MessageType.TASK)
    state = make_state()

    for i in range(3):
        msg = make_message(f"задача {i}")
        mock_item = MagicMock()
        mock_item.id = f"item-{i}"
        task_svc = MagicMock(spec=TaskService)
        task_svc.save = AsyncMock(return_value=SavedTask(item=mock_item))

        await handle_text(msg, state=state, classifier=classifier, task_service=task_svc, lang="ru")
        msg.answer.assert_awaited_once()
        assert "Задача сохранена" in msg.answer.call_args[0][0]

    # FSM should never be entered
    state.set_state.assert_not_awaited()
