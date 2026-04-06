"""Voice transcription via OpenAI Whisper API."""

import io
import logging

import openai

from bot.config import Config
from bot.exceptions import TranscriptionError

logger = logging.getLogger(__name__)


class TranscriptionService:
    """Transcribe audio bytes to text using OpenAI Whisper."""

    def __init__(self, config: Config) -> None:
        self._client = openai.AsyncOpenAI(api_key=config.openai_api_key)

    async def transcribe(self, audio_bytes: bytes) -> str:
        """Send OGG audio to Whisper and return the transcript text."""
        try:
            response = await self._client.audio.transcriptions.create(
                model="whisper-1",
                file=("voice.ogg", io.BytesIO(audio_bytes), "audio/ogg"),
            )
            return response.text
        except openai.OpenAIError as exc:
            logger.error("Whisper transcription failed: %s", exc)
            raise TranscriptionError(str(exc)) from exc
