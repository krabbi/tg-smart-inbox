"""Integration test: commands are always handled even when FSM dialog is active (AC 2).

This verifies that /cancel, /list etc. are processed correctly when the user is
in the waiting_for_time FSM state, because the commands router is registered
before the reminders router in the dispatcher.
"""

from unittest.mock import AsyncMock, MagicMock

from aiogram.fsm.context import FSMContext
from aiogram.types import Message, User

from bot.handlers.commands import cmd_cancel
from bot.handlers.reminders import ReminderStates


async def test_cancel_command_clears_fsm_during_waiting_for_time() -> None:
    """Verify /cancel works when FSM is in waiting_for_time state."""
    state = MagicMock(spec=FSMContext)
    state.get_state = AsyncMock(return_value=ReminderStates.waiting_for_time.state)
    state.clear = AsyncMock()

    user = MagicMock(spec=User)
    user.id = 1
    msg = MagicMock(spec=Message)
    msg.from_user = user
    msg.answer = AsyncMock()

    await cmd_cancel(msg, state=state, lang="ru")

    state.clear.assert_awaited_once()
    msg.answer.assert_awaited_once()
    assert "Отменено" in msg.answer.call_args[0][0]


async def test_cancel_command_when_no_active_state() -> None:
    """Verify /cancel gives appropriate message when no FSM state is active."""
    state = MagicMock(spec=FSMContext)
    state.get_state = AsyncMock(return_value=None)
    state.clear = AsyncMock()

    user = MagicMock(spec=User)
    user.id = 1
    msg = MagicMock(spec=Message)
    msg.from_user = user
    msg.answer = AsyncMock()

    await cmd_cancel(msg, state=state, lang="ru")

    state.clear.assert_not_awaited()
    msg.answer.assert_awaited_once()
    assert "Нет активного" in msg.answer.call_args[0][0]


def test_router_registration_order_commands_before_reminders() -> None:
    """Verify that commands router is registered before reminders router.

    This is critical: commands like /cancel must be checked before the FSM
    state handler in reminders (waiting_for_time), otherwise /cancel would be
    swallowed by the reminder time parser.

    Routers are module-level singletons and can only be attached to one parent,
    so we inspect the source of create_dispatcher to verify include_router call
    order instead of creating a real Dispatcher.
    """
    import inspect

    from bot.bot import create_dispatcher

    source = inspect.getsource(create_dispatcher)
    lines = source.splitlines()

    # Collect include_router calls in order
    include_lines: list[str] = [line.strip() for line in lines if "include_router(" in line]

    # Extract router module names from lines like "dp.include_router(commands.router)"
    router_order: list[str] = []
    for line in include_lines:
        # Extract the part between "(" and ".router"
        start = line.index("(") + 1
        end = line.index(".router")
        router_order.append(line[start:end].strip())

    assert "commands" in router_order, "commands router not registered in create_dispatcher"
    assert "reminders" in router_order, "reminders router not registered in create_dispatcher"
    assert "messages" in router_order, "messages router not registered in create_dispatcher"

    commands_idx = router_order.index("commands")
    reminders_idx = router_order.index("reminders")
    messages_idx = router_order.index("messages")

    assert commands_idx < reminders_idx, (
        f"commands router (idx={commands_idx}) must be before "
        f"reminders router (idx={reminders_idx})"
    )
    assert reminders_idx < messages_idx, (
        f"reminders router (idx={reminders_idx}) must be before "
        f"messages router (idx={messages_idx})"
    )
