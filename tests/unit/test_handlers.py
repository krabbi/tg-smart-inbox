from unittest.mock import AsyncMock, MagicMock

from aiogram.types import Message, User

from bot.handlers.commands import cmd_start
from bot.handlers.messages import handle_document, handle_photo, handle_text


def make_message(text: str | None = None, user_id: int = 123, forwarded: bool = False) -> Message:
    """Create a minimal mock Message."""
    user = MagicMock(spec=User)
    user.id = user_id
    message = MagicMock(spec=Message)
    message.from_user = user
    message.text = text
    message.forward_origin = MagicMock() if forwarded else None
    message.answer = AsyncMock()
    return message


async def test_cmd_start_sends_welcome() -> None:
    message = make_message()
    await cmd_start(message)
    message.answer.assert_awaited_once()
    call_text = message.answer.call_args[0][0]
    assert "инбокс" in call_text.lower() or "привет" in call_text.lower()


async def test_handle_text_replies() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from aiogram.fsm.context import FSMContext

    state = MagicMock(spec=FSMContext)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    message = make_message(text="Hello bot")
    await handle_text(message, state=state)
    message.answer.assert_awaited_once()


async def test_handle_text_forwarded_replies() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from aiogram.fsm.context import FSMContext

    state = MagicMock(spec=FSMContext)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    message = make_message(text="Forwarded text", forwarded=True)
    await handle_text(message, state=state)
    message.answer.assert_awaited_once()


async def test_handle_photo_replies() -> None:
    message = make_message()
    await handle_photo(message)
    message.answer.assert_awaited_once()
    assert "Фото" in message.answer.call_args[0][0]


async def test_handle_document_replies() -> None:
    message = make_message()
    await handle_document(message)
    message.answer.assert_awaited_once()
    assert "Файл" in message.answer.call_args[0][0]


async def test_handle_text_without_user() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from aiogram.fsm.context import FSMContext

    state = MagicMock(spec=FSMContext)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    message = make_message(text="hi")
    message.from_user = None
    await handle_text(message, state=state)
    message.answer.assert_awaited_once()
