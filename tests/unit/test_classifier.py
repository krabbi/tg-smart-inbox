from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.services.classifier import _CLASSIFY_PROMPT, ClassifierService, MessageType
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


# ── Markdown fence stripping ─────────────────────────────────────────────────


async def test_json_in_markdown_fence_parsed_correctly() -> None:
    svc = ClassifierService(make_claude('```json\n{"type": "idea"}\n```'))
    result = await svc.classify("вертолёт с колёсами вместо винтов")
    assert result == MessageType.IDEA


async def test_json_in_plain_fence_parsed_correctly() -> None:
    svc = ClassifierService(make_claude('```\n{"type": "task"}\n```'))
    result = await svc.classify("купить молоко")
    assert result == MessageType.TASK


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


# ── Language propagation ─────────────────────────────────────────────────────


async def test_classify_prompt_template_is_language_neutral() -> None:
    """The prompt template must reference ``{language}`` and not hardcode Russian."""
    assert "{language}" in _CLASSIFY_PROMPT
    assert "Russian" not in _CLASSIFY_PROMPT


async def test_classify_passes_russian_into_prompt_when_lang_ru() -> None:
    """lang='ru' must surface as 'Russian' in the prompt sent to Claude."""
    client = MagicMock(spec=ClaudeClient)
    client.complete = AsyncMock(return_value='{"type": "task"}')
    svc = ClassifierService(client)

    await svc.classify("купить молоко", lang="ru")

    sent_prompt = client.complete.await_args.args[0]
    assert "Russian" in sent_prompt
    assert "English" not in sent_prompt


async def test_classify_passes_english_into_prompt_when_lang_en() -> None:
    """lang='en' must surface as 'English' in the prompt sent to Claude."""
    client = MagicMock(spec=ClaudeClient)
    client.complete = AsyncMock(return_value='{"type": "note"}')
    svc = ClassifierService(client)

    await svc.classify("some note text", lang="en")

    sent_prompt = client.complete.await_args.args[0]
    assert "English" in sent_prompt
    assert "Russian" not in sent_prompt


async def test_classify_default_lang_is_english() -> None:
    """Omitting lang should default to English, not Russian."""
    client = MagicMock(spec=ClaudeClient)
    client.complete = AsyncMock(return_value='{"type": "note"}')
    svc = ClassifierService(client)

    await svc.classify("some text")

    sent_prompt = client.complete.await_args.args[0]
    assert "English" in sent_prompt
    assert "Russian" not in sent_prompt


async def test_classify_unknown_lang_falls_back_to_english() -> None:
    """An unsupported language code must not crash and must fall back to English."""
    client = MagicMock(spec=ClaudeClient)
    client.complete = AsyncMock(return_value='{"type": "note"}')
    svc = ClassifierService(client)

    result = await svc.classify("some text", lang="fr")

    assert result == MessageType.NOTE
    sent_prompt = client.complete.await_args.args[0]
    assert "English" in sent_prompt
