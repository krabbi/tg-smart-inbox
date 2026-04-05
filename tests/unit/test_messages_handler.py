from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.types import Message, User

from bot.handlers.messages import _extract_url, handle_text
from bot.services.classifier import ClassifierService, MessageType
from bot.services.link_service import LinkService


def make_message(text: str, user_id: int = 1, forwarded: bool = False) -> Message:
    user = MagicMock(spec=User)
    user.id = user_id
    msg = MagicMock(spec=Message)
    msg.from_user = user
    msg.text = text
    msg.forward_origin = MagicMock() if forwarded else None
    msg.answer = AsyncMock()
    return msg


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
    await handle_text(msg, classifier=None)
    msg.answer.assert_awaited_once()


# ── handle_text with classifier ──────────────────────────────────────────────

async def test_handle_text_link_calls_link_handler() -> None:
    msg = make_message("https://example.com")
    classifier = make_classifier(MessageType.LINK)
    link_service = MagicMock(spec=LinkService)

    with patch("bot.handlers.links.handle_link_message", new=AsyncMock()) as mock_handle:
        await handle_text(msg, classifier=classifier, link_service=link_service)
        mock_handle.assert_awaited_once()


async def test_handle_text_task_gives_type_reply() -> None:
    msg = make_message("купить молоко")
    classifier = make_classifier(MessageType.TASK)
    await handle_text(msg, classifier=classifier)
    msg.answer.assert_awaited_once()
    assert "task" in msg.answer.call_args[0][0]


async def test_handle_text_note_gives_type_reply() -> None:
    msg = make_message("Байкал — самое глубокое озеро")
    classifier = make_classifier(MessageType.NOTE)
    await handle_text(msg, classifier=classifier)
    msg.answer.assert_awaited_once()


async def test_handle_text_idea_gives_type_reply() -> None:
    msg = make_message("хочу сделать приложение")
    classifier = make_classifier(MessageType.IDEA)
    await handle_text(msg, classifier=classifier)
    msg.answer.assert_awaited_once()


async def test_handle_text_link_without_link_service_gives_stub() -> None:
    msg = make_message("https://example.com")
    classifier = make_classifier(MessageType.LINK)
    await handle_text(msg, classifier=classifier, link_service=None)
    msg.answer.assert_awaited_once()
