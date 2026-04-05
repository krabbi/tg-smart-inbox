import anthropic

from bot.config import Config
from bot.exceptions import ClassificationError


class ClaudeClient:
    """Thin async wrapper around the Anthropic Claude API."""

    MODEL = "claude-haiku-4-5-20251001"
    MAX_TOKENS = 256

    def __init__(self, config: Config) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)

    async def complete(self, prompt: str) -> str:
        """Send a prompt and return the text response.

        Raises ClassificationError if the API call fails.
        """
        try:
            message = await self._client.messages.create(
                model=self.MODEL,
                max_tokens=self.MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text  # type: ignore[union-attr]
        except Exception as exc:
            raise ClassificationError(f"Claude API error: {exc}") from exc
