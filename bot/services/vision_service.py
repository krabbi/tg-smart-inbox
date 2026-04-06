import base64
import json
import logging
from dataclasses import dataclass

import anthropic

from bot.config import Config

logger = logging.getLogger(__name__)

_VALID_CATEGORIES = {"receipt", "document", "screenshot", "photo", "meme", "other"}
_SUPPORTED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

_ANALYZE_PROMPT = """\
Analyze this image and return a JSON object with:
- "category": one of: receipt, document, screenshot, photo, meme, other
- "description": 1-2 sentence description of what this is (in the same language as any text in the image, default Russian)

Respond with JSON only. No explanation outside the JSON.

Category definitions:
- receipt: purchase receipts, invoices, payment confirmations
- document: official papers, certificates, forms, contracts
- screenshot: screen captures from devices, apps, websites
- photo: real-world photos of people, places, objects, food, nature
- meme: humorous images, meme templates, funny screenshots
- other: anything that doesn't fit above
"""


@dataclass(frozen=True)
class MediaAnalysis:
    """Result of analyzing a media file with Claude Vision."""

    category: str
    description: str


class VisionService:
    """Categorize and describe images using Claude Vision."""

    MODEL = "claude-haiku-4-5-20251001"

    def __init__(self, config: Config) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)

    async def analyze(self, image_bytes: bytes, media_type: str = "image/jpeg") -> MediaAnalysis:
        """Analyze image bytes and return category + description.

        Falls back to category 'other' if Claude returns an unknown category or
        if the media type is not supported by Claude Vision.
        """
        if media_type not in _SUPPORTED_MEDIA_TYPES:
            logger.warning(
                "Unsupported media type for vision analysis: %s, defaulting to 'other'", media_type
            )
            return MediaAnalysis(
                category="other", description="Формат файла не поддерживается для анализа."
            )
        b64 = base64.standard_b64encode(image_bytes).decode()
        try:
            response = await self._client.messages.create(
                model=self.MODEL,
                max_tokens=256,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": b64,
                                },
                            },
                            {"type": "text", "text": _ANALYZE_PROMPT},
                        ],
                    }
                ],
            )
            return self._parse_response(response.content[0].text)  # type: ignore[union-attr]
        except Exception:
            logger.exception("Vision analysis failed, falling back to 'other'")
            return MediaAnalysis(category="other", description="Не удалось проанализировать файл.")

    @staticmethod
    def _parse_response(raw: str) -> MediaAnalysis:
        """Parse Claude's JSON response into MediaAnalysis, defaulting to 'other'."""
        try:
            data = json.loads(raw.strip())
            category = str(data.get("category", "other")).lower()
            if category not in _VALID_CATEGORIES:
                category = "other"
            description = str(data.get("description", "Медиафайл"))
            return MediaAnalysis(category=category, description=description)
        except (json.JSONDecodeError, AttributeError):
            return MediaAnalysis(category="other", description="Медиафайл")
