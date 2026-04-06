"""Unit tests for TranscriptionService."""

from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from bot.exceptions import TranscriptionError
from bot.services.transcription_service import TranscriptionService


@pytest.fixture
def fake_config(fake_config):  # type: ignore[override]
    fake_config.openai_api_key = "sk-fake-openai-key"
    return fake_config


async def test_transcribe_returns_text(fake_config) -> None:
    svc = TranscriptionService(fake_config)
    mock_response = MagicMock()
    mock_response.text = "купить молоко"

    with patch.object(
        svc._client.audio.transcriptions, "create", new=AsyncMock(return_value=mock_response)
    ):
        result = await svc.transcribe(b"fake-audio-bytes")

    assert result == "купить молоко"


async def test_transcribe_sends_ogg_file(fake_config) -> None:
    svc = TranscriptionService(fake_config)
    mock_response = MagicMock()
    mock_response.text = "test"
    mock_create = AsyncMock(return_value=mock_response)

    with patch.object(svc._client.audio.transcriptions, "create", new=mock_create):
        await svc.transcribe(b"audio-data")

    call_kwargs = mock_create.call_args[1]
    assert call_kwargs["model"] == "whisper-1"
    filename, buf, mime = call_kwargs["file"]
    assert filename == "voice.ogg"
    assert mime == "audio/ogg"
    assert buf.read() == b"audio-data"


async def test_transcribe_raises_transcription_error_on_api_failure(fake_config) -> None:
    svc = TranscriptionService(fake_config)

    with (
        patch.object(
            svc._client.audio.transcriptions,
            "create",
            new=AsyncMock(side_effect=openai.OpenAIError("quota exceeded")),
        ),
        pytest.raises(TranscriptionError),
    ):
        await svc.transcribe(b"audio-bytes")
