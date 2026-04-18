from unittest.mock import AsyncMock, MagicMock

from bot.config import Config
from bot.services.vision_service import VisionService


def make_config() -> Config:
    return Config(telegram_bot_token="fake", anthropic_api_key="sk-ant-fake")


def make_service(response: str) -> VisionService:
    svc = VisionService(make_config())
    mock_content = MagicMock()
    mock_content.text = response
    mock_response = MagicMock()
    mock_response.content = [mock_content]
    svc._client = MagicMock()
    svc._client.messages.create = AsyncMock(return_value=mock_response)
    return svc


async def test_analyze_receipt() -> None:
    svc = make_service('{"category": "receipt", "description": "Purchase receipt from store"}')
    result = await svc.analyze(b"fake image bytes")
    assert result.category == "receipt"
    assert result.description == "Purchase receipt from store"


async def test_analyze_document() -> None:
    svc = make_service('{"category": "document", "description": "Official certificate"}')
    result = await svc.analyze(b"fake bytes")
    assert result.category == "document"


async def test_analyze_screenshot() -> None:
    svc = make_service('{"category": "screenshot", "description": "App screenshot"}')
    result = await svc.analyze(b"fake bytes")
    assert result.category == "screenshot"


async def test_analyze_unknown_category_falls_back_to_other() -> None:
    svc = make_service('{"category": "unicorn", "description": "Unknown thing"}')
    result = await svc.analyze(b"fake bytes")
    assert result.category == "other"


async def test_analyze_malformed_json_falls_back_to_other() -> None:
    svc = make_service("not json")
    result = await svc.analyze(b"fake bytes")
    assert result.category == "other"


async def test_analyze_api_error_falls_back_to_other() -> None:
    svc = VisionService(make_config())
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


async def test_analyze_unsupported_media_type_falls_back_to_other() -> None:
    svc = VisionService(make_config())
    svc._client = MagicMock()
    result = await svc.analyze(b"pdf bytes", media_type="application/pdf")
    assert result.category == "other"
    # Fallback description is taken from the i18n table (default language, EN).
    assert "not supported" in result.description
    svc._client.messages.create.assert_not_called()


async def test_analyze_passes_media_type() -> None:
    svc = VisionService(make_config())
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
