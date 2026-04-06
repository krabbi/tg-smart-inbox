from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.services.classifier import ClassifierService, MessageType
from bot.services.claude_client import ClaudeClient


def make_claude(response: str) -> ClaudeClient:
    """Create a mock ClaudeClient that returns the given response."""
    client = MagicMock(spec=ClaudeClient)
    client.complete = AsyncMock(return_value=response)
    return client


# ── Fast-path rules (no API call) ────────────────────────────────────────────


async def test_media_short_circuits() -> None:
    claude = MagicMock(spec=ClaudeClient)
    svc = ClassifierService(claude)
    result = await svc.classify("some text", has_media=True)
    assert result == MessageType.MEDIA
    claude.complete.assert_not_called()  # type: ignore[attr-defined]


async def test_url_is_link() -> None:
    claude = MagicMock(spec=ClaudeClient)
    svc = ClassifierService(claude)
    result = await svc.classify("https://example.com", has_media=False)
    assert result == MessageType.LINK
    claude.complete.assert_not_called()  # type: ignore[attr-defined]


async def test_url_with_surrounding_text_is_link() -> None:
    claude = MagicMock(spec=ClaudeClient)
    svc = ClassifierService(claude)
    result = await svc.classify("Посмотри https://habr.com/article/123 интересная статья")
    assert result == MessageType.LINK
    claude.complete.assert_not_called()  # type: ignore[attr-defined]


async def test_http_url_is_link() -> None:
    claude = MagicMock(spec=ClaudeClient)
    svc = ClassifierService(claude)
    result = await svc.classify("http://example.com/page")
    assert result == MessageType.LINK
    claude.complete.assert_not_called()  # type: ignore[attr-defined]


# ── Claude-backed classification ─────────────────────────────────────────────


async def test_claude_task_response() -> None:
    svc = ClassifierService(make_claude('{"type": "task"}'))
    result = await svc.classify("купить молоко")
    assert result == MessageType.TASK


async def test_claude_idea_response() -> None:
    svc = ClassifierService(make_claude('{"type": "idea"}'))
    result = await svc.classify("хочу сделать приложение для учёта расходов")
    assert result == MessageType.IDEA


async def test_claude_note_response() -> None:
    svc = ClassifierService(make_claude('{"type": "note"}'))
    result = await svc.classify("Пушкин родился в 1799 году")
    assert result == MessageType.NOTE


# ── Fallback on malformed response ───────────────────────────────────────────


async def test_malformed_json_falls_back_to_note() -> None:
    svc = ClassifierService(make_claude("not valid json"))
    result = await svc.classify("some text")
    assert result == MessageType.NOTE


async def test_missing_type_field_falls_back_to_note() -> None:
    svc = ClassifierService(make_claude('{"category": "task"}'))
    result = await svc.classify("some text")
    assert result == MessageType.NOTE


async def test_unknown_type_value_falls_back_to_note() -> None:
    svc = ClassifierService(make_claude('{"type": "unknown_type"}'))
    result = await svc.classify("some text")
    assert result == MessageType.NOTE


async def test_claude_api_error_falls_back_to_note() -> None:
    client = MagicMock(spec=ClaudeClient)
    client.complete = AsyncMock(side_effect=Exception("API down"))
    svc = ClassifierService(client)
    result = await svc.classify("тест")
    assert result == MessageType.NOTE


# ── Russian-language samples ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "надо позвонить маме",
        "не забыть оплатить квартиру до пятницы",
        "сходить в спортзал завтра утром",
    ],
)
async def test_russian_tasks(text: str) -> None:
    svc = ClassifierService(make_claude('{"type": "task"}'))
    result = await svc.classify(text)
    assert result == MessageType.TASK


@pytest.mark.parametrize(
    "text",
    [
        "хочу написать книгу о путешествиях",
        "идея: сделать бота для напоминаний",
        "а что если открыть кофейню с коворкингом",
    ],
)
async def test_russian_ideas(text: str) -> None:
    svc = ClassifierService(make_claude('{"type": "idea"}'))
    result = await svc.classify(text)
    assert result == MessageType.IDEA


@pytest.mark.parametrize(
    "text",
    [
        "Байкал — самое глубокое озеро в мире",
        "встреча с командой прошла хорошо",
        "прочитал интересную статью о машинном обучении",
    ],
)
async def test_russian_notes(text: str) -> None:
    svc = ClassifierService(make_claude('{"type": "note"}'))
    result = await svc.classify(text)
    assert result == MessageType.NOTE
