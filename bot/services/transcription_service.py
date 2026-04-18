"""Voice transcription via Groq Whisper API."""

import io
import logging

import groq

from bot.config import Config
from bot.exceptions import TranscriptionError

logger = logging.getLogger(__name__)


class TranscriptionService:
    """Transcribe audio bytes to text using Groq Whisper Large v3."""

    def __init__(self, config: Config) -> None:
        self._client = groq.AsyncGroq(api_key=config.groq_api_key)

    async def transcribe(self, audio_bytes: bytes) -> str:
        """Send OGG audio to Groq Whisper and return the transcript text.

        On failure ``TranscriptionError`` is raised carrying an i18n key as its
        ``args[0]`` (via ``str(exc)``). Handlers translate the key against the
        user's language before replying.
        """
        try:
            response = await self._client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=("voice.ogg", io.BytesIO(audio_bytes), "audio/ogg"),
            )
            return response.text
        except groq.AuthenticationError as exc:
            logger.error("Groq authentication failed: %s", exc)
            raise TranscriptionError("transcription_bad_key") from exc
        except groq.APIConnectionError as exc:
            logger.error("Groq connection error: %s", exc)
            raise TranscriptionError("transcription_unavailable") from exc
        except groq.GroqError as exc:
            logger.error("Groq API error: %s", exc)
            raise TranscriptionError("transcription_failed") from exc
