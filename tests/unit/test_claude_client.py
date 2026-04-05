from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.config import Config
from bot.exceptions import ClassificationError
from bot.services.claude_client import ClaudeClient


def make_config() -> Config:
    return Config(
        telegram_bot_token="fake",
        anthropic_api_key="sk-ant-fake",
    )


async def test_complete_returns_text() -> None:
    config = make_config()
    client = ClaudeClient(config)

    mock_content = MagicMock()
    mock_content.text = '{"type": "task"}'
    mock_response = MagicMock()
    mock_response.content = [mock_content]

    with patch.object(client._client.messages, "create", new=AsyncMock(return_value=mock_response)):
        result = await client.complete("classify this")

    assert result == '{"type": "task"}'


async def test_complete_raises_classification_error_on_api_failure() -> None:
    config = make_config()
    client = ClaudeClient(config)

    with patch.object(
        client._client.messages,
        "create",
        new=AsyncMock(side_effect=Exception("rate limit")),
    ), pytest.raises(ClassificationError, match="Claude API error"):
        await client.complete("classify this")
