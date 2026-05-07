from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.config import Config
from bot.services.vision_service import _ANALYZE_PROMPT, VisionService


@pytest.fixture
def make_service(fake_config: Config):
    def _factory(response: str) -> VisionService:
        svc = VisionService(fake_config)
        mock_content = MagicMock()
        mock_content.text = response
        mock_response = MagicMock()
        mock_response.content = [mock_content]
        svc._client = MagicMock()
        svc._client.messages.create = AsyncMock(return_value=mock_response)
        return svc

    return _factory


async def test_analyze_receipt(make_service) -> None:
    svc = make_service('{"category": "receipt", "description": "Purchase receipt from store"}')
    result = await svc.analyze(b"fake image bytes")
    assert result.category == "receipt"
    assert result.description == "Purchase receipt from store"


async def test_analyze_document(make_service) -> None:
    svc = make_service('{"category": "document", "description": "Official certificate"}')
    result = await svc.analyze(b"fake bytes")
    assert result.category == "document"


async def test_analyze_screenshot(make_service) -> None:
    svc = make_service('{"category": "screenshot", "description": "App screenshot"}')
    result = await svc.analyze(b"fake bytes")
    assert result.category == "screenshot"


async def test_analyze_unknown_category_falls_back_to_other(make_service) -> None:
    svc = make_service('{"category": "unicorn", "description": "Unknown thing"}')
    result = await svc.analyze(b"fake bytes")
    assert result.category == "other"


async def test_analyze_malformed_json_falls_back_to_other(make_service) -> None:
    svc = make_service("not json")
    result = await svc.analyze(b"fake bytes")
    assert result.category == "other"


async def test_analyze_api_error_falls_back_to_other(fake_config: Config) -> None:
    svc = VisionService(fake_config)
    svc._client = MagicMock()
    svc._client.messages.create = AsyncMock(side_effect=Exception("API error"))
    result = await svc.analyze(b"fake bytes")
    assert result.category == "other"
    # The fallback description is taken from the i18n table (default language).
    assert "Failed to analyze" in result.description


def test_parse_response_all_categories() -> None:
    for cat in ("receipt", "document", "screenshot", "photo", "meme", "other"):
        raw = f'{{"category": "{cat}", "description": "test"}}'
        result = VisionService._parse_response(raw)
        assert result.category == cat


def test_parse_response_case_insensitive() -> None:
    result = VisionService._parse_response('{"category": "RECEIPT", "description": "test"}')
    assert result.category == "receipt"


def test_parse_response_strips_json_code_fence() -> None:
    raw = '```json\n{"category": "photo", "description": "A nice photo"}\n```'
    result = VisionService._parse_response(raw)
    assert result.category == "photo"
    assert result.description == "A nice photo"


def test_parse_response_strips_plain_code_fence() -> None:
    raw = '```\n{"category": "meme", "description": "Funny meme"}\n```'
    result = VisionService._parse_response(raw)
    assert result.category == "meme"
    assert result.description == "Funny meme"


async def test_analyze_handles_code_fenced_response(make_service) -> None:
    svc = make_service('```json\n{"category": "screenshot", "description": "A browser tab"}\n```')
    result = await svc.analyze(b"fake bytes")
    assert result.category == "screenshot"
    assert result.description == "A browser tab"


async def test_analyze_unsupported_media_type_falls_back_to_other(fake_config: Config) -> None:
    svc = VisionService(fake_config)
    svc._client = MagicMock()
    result = await svc.analyze(b"pdf bytes", media_type="application/pdf")
    assert result.category == "other"
    # Fallback description is taken from the i18n table (default language, EN).
    assert "not supported" in result.description
    svc._client.messages.create.assert_not_called()


async def test_analyze_passes_media_type(fake_config: Config) -> None:
    svc = VisionService(fake_config)
    mock_content = MagicMock()
    mock_content.text = '{"category": "document", "description": "PNG doc"}'
    mock_response = MagicMock()
    mock_response.content = [mock_content]
    svc._client = MagicMock()
    svc._client.messages.create = AsyncMock(return_value=mock_response)

    result = await svc.analyze(b"png bytes", media_type="image/png")
    assert result.category == "document"
    call_kwargs = svc._client.messages.create.call_args[1]
    msg_content = call_kwargs["messages"][0]["content"]
    assert msg_content[0]["source"]["media_type"] == "image/png"


# ── Language propagation ─────────────────────────────────────────────────────


async def test_analyze_prompt_template_is_language_neutral() -> None:
    """The prompt template must use ``{language}`` and not hardcode Russian."""
    assert "{language}" in _ANALYZE_PROMPT
    assert "Russian" not in _ANALYZE_PROMPT


async def test_analyze_forwards_russian_into_prompt(make_service) -> None:
    """lang='ru' must surface as 'Russian' in the text prompt sent to Claude."""
    svc = make_service('{"category": "photo", "description": "Фотография улицы"}')
    await svc.analyze(b"image bytes", media_type="image/jpeg", lang="ru")

    call_kwargs = svc._client.messages.create.call_args[1]
    prompt_text = call_kwargs["messages"][0]["content"][1]["text"]
    assert "Russian" in prompt_text
    assert "English" not in prompt_text


async def test_analyze_forwards_english_into_prompt(make_service) -> None:
    """lang='en' must surface as 'English' in the text prompt sent to Claude."""
    svc = make_service('{"category": "photo", "description": "Street photo"}')
    await svc.analyze(b"image bytes", media_type="image/jpeg", lang="en")

    call_kwargs = svc._client.messages.create.call_args[1]
    prompt_text = call_kwargs["messages"][0]["content"][1]["text"]
    assert "English" in prompt_text
    assert "Russian" not in prompt_text


async def test_analyze_default_lang_is_english(make_service) -> None:
    """Omitting lang falls back to English in the Claude prompt."""
    svc = make_service('{"category": "photo", "description": "A photo"}')
    await svc.analyze(b"image bytes", media_type="image/jpeg")

    call_kwargs = svc._client.messages.create.call_args[1]
    prompt_text = call_kwargs["messages"][0]["content"][1]["text"]
    assert "English" in prompt_text
    assert "Russian" not in prompt_text


async def test_analyze_unsupported_media_uses_localized_fallback(fake_config: Config) -> None:
    """Unsupported media fallback description must honour the caller's language."""
    svc = VisionService(fake_config)
    svc._client = MagicMock()
    result_ru = await svc.analyze(b"pdf bytes", media_type="application/pdf", lang="ru")
    result_en = await svc.analyze(b"pdf bytes", media_type="application/pdf", lang="en")
    # The i18n tables return different strings per language — compare directly.
    assert result_ru.description != result_en.description
    assert "не поддерживается" in result_ru.description
    assert "not supported" in result_en.description


async def test_analyze_api_error_uses_localized_fallback(fake_config: Config) -> None:
    """API error fallback description must honour the caller's language."""
    svc = VisionService(fake_config)
    svc._client = MagicMock()
    svc._client.messages.create = AsyncMock(side_effect=Exception("API boom"))
    result_ru = await svc.analyze(b"bytes", media_type="image/jpeg", lang="ru")
    assert "Не удалось проанализировать" in result_ru.description

    svc._client.messages.create = AsyncMock(side_effect=Exception("API boom"))
    result_en = await svc.analyze(b"bytes", media_type="image/jpeg", lang="en")
    assert "Failed to analyze" in result_en.description
