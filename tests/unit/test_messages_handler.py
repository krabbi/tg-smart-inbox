from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.fsm.context import FSMContext
from aiogram.types import Message, User

from bot.handlers.messages import _is_suggestion_query, handle_text
from bot.services.classifier import ClassifierService, MessageType
from bot.services.idea_service import IdeaService, SavedIdea
from bot.services.link_service import LinkService
from bot.services.note_service import NoteService, SavedNote
from bot.services.task_service import SavedTask, TaskService
from bot.utils.text import extract_url as _extract_url


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

    with patch("bot.handlers.links.handle_link_message", new=AsyncMock()) as mock_handle:
        await handle_text(msg, state=make_state(), classifier=classifier, link_service=link_service)
        mock_handle.assert_awaited_once()


async def test_handle_text_task_saves_and_asks_reminder() -> None:
    msg = make_message("купить молоко")
    classifier = make_classifier(MessageType.TASK)
    state = make_state()

    mock_item = MagicMock()
    mock_item.id = "item-uuid"
    task_svc = MagicMock(spec=TaskService)
    task_svc.save = AsyncMock(return_value=SavedTask(item=mock_item))

    with patch("bot.handlers.reminders.ask_reminder", new=AsyncMock()) as mock_ask:
        await handle_text(msg, state=state, classifier=classifier, task_service=task_svc)
        mock_ask.assert_awaited_once()
        assert mock_ask.call_args[1]["item_id"] == "item-uuid"


async def test_handle_text_task_save_error_sends_error_reply() -> None:
    msg = make_message("купить молоко")
    classifier = make_classifier(MessageType.TASK)
    task_svc = MagicMock(spec=TaskService)
    task_svc.save = AsyncMock(side_effect=Exception("DB error"))

    await handle_text(msg, state=make_state(), classifier=classifier, task_service=task_svc)
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

    await handle_text(msg, state=make_state(), classifier=classifier, note_service=note_svc)
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
    idea_svc.save_idea = AsyncMock(return_value=MagicMock(spec=SavedIdea, idea=mock_idea))

    await handle_text(msg, state=make_state(), classifier=classifier, idea_service=idea_svc)
    msg.answer.assert_awaited_once()
    reply = msg.answer.call_args[0][0]
    assert "💡" in reply
    assert "#app" in reply


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

    await handle_text(msg, state=make_state(), classifier=classifier, idea_service=idea_svc)
    msg.answer.assert_awaited_once()
    assert "Не удалось" in msg.answer.call_args[0][0]


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
