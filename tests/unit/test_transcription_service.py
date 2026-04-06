"""Unit tests for TranscriptionService."""

from unittest.mock import AsyncMock, MagicMock, patch

import groq
import pytest

from bot.exceptions import TranscriptionError
from bot.services.transcription_service import TranscriptionService


@pytest.fixture
def fake_config(fake_config):  # type: ignore[override]
    fake_config.groq_api_key = "gsk_fake_groq_key"
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


async def test_transcribe_sends_ogg_file_with_correct_model(fake_config) -> None:
    svc = TranscriptionService(fake_config)
    mock_response = MagicMock()
    mock_response.text = "test"
    mock_create = AsyncMock(return_value=mock_response)

    with patch.object(svc._client.audio.transcriptions, "create", new=mock_create):
        await svc.transcribe(b"audio-data")

    call_kwargs = mock_create.call_args[1]
    assert call_kwargs["model"] == "whisper-large-v3"
    filename, buf, mime = call_kwargs["file"]
    assert filename == "voice.ogg"
    assert mime == "audio/ogg"
    assert buf.read() == b"audio-data"


async def test_transcribe_auth_error_raises_with_key_message(fake_config) -> None:
    svc = TranscriptionService(fake_config)

    with (
        patch.object(
            svc._client.audio.transcriptions,
            "create",
            new=AsyncMock(
                side_effect=groq.AuthenticationError("invalid key", response=MagicMock(), body={})
            ),
        ),
        pytest.raises(TranscriptionError) as exc_info,
    ):
        await svc.transcribe(b"audio-bytes")

    assert "GROQ_API_KEY" in str(exc_info.value)


async def test_transcribe_connection_error_raises_with_unavailable_message(fake_config) -> None:
    svc = TranscriptionService(fake_config)

    with (
        patch.object(
            svc._client.audio.transcriptions,
            "create",
            new=AsyncMock(side_effect=groq.APIConnectionError(request=MagicMock())),
        ),
        pytest.raises(TranscriptionError) as exc_info,
    ):
        await svc.transcribe(b"audio-bytes")

    assert "недоступен" in str(exc_info.value)


async def test_transcribe_generic_groq_error_raises_transcription_error(fake_config) -> None:
    svc = TranscriptionService(fake_config)

    with (
        patch.object(
            svc._client.audio.transcriptions,
            "create",
            new=AsyncMock(
                side_effect=groq.InternalServerError("server error", response=MagicMock(), body={})
            ),
        ),
        pytest.raises(TranscriptionError),
    ):
        await svc.transcribe(b"audio-bytes")
