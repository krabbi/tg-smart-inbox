import json
import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.idea import Idea, IdeaComplexity, IdeaEffort
from bot.models.item import Item, ItemType
from bot.repositories.idea_repository import IdeaRepository
from bot.repositories.item_repository import ItemRepository
from bot.services.claude_client import ClaudeClient

logger = logging.getLogger(__name__)

_TAG_PROMPT = """\
Extract 1-5 short tags (keywords) from the following idea.
Respond with a JSON array of lowercase strings only. No explanation.

Example: ["mobile", "app", "startup"]

Idea: """

_CLASSIFY_PROMPT = """\
Estimate the complexity and effort required to execute the following idea.

Complexity options: simple, medium, complex
Effort options:
  quick    = less than 1 hour
  halfday  = 1-4 hours
  day      = 4-8 hours
  longterm = days or more

Respond with JSON only, no explanation:
{"complexity": "simple|medium|complex", "effort": "quick|halfday|day|longterm"}

Idea: """

_COMPLEXITY_MAP: dict[str, IdeaComplexity] = {
    "simple": IdeaComplexity.simple,
    "medium": IdeaComplexity.medium,
    "complex": IdeaComplexity.complex,
}

_EFFORT_MAP: dict[str, IdeaEffort] = {
    "quick": IdeaEffort.quick,
    "halfday": IdeaEffort.halfday,
    "day": IdeaEffort.day,
    "longterm": IdeaEffort.longterm,
}

_SUGGEST_PROMPT = """\
The user has the following saved ideas:

{ideas}

User query: "{query}"

Suggest 1-3 ideas from the list that would be worth working on. Explain briefly \
why each is a good choice. Respond in the same language as the user query. \
If the list is empty, say so politely.
"""


@dataclass(frozen=True)
class SavedIdea:
    """Result of saving an idea."""

    item: Item
    idea: Idea


class IdeaService:
    """Save ideas with AI-extracted tags and generate suggestions from the backlog."""

    def __init__(
        self,
        session: AsyncSession,
        item_repo: ItemRepository,
        idea_repo: IdeaRepository,
        claude: ClaudeClient,
    ) -> None:
        self._session = session
        self._item_repo = item_repo
        self._idea_repo = idea_repo
        self._claude = claude

    async def save_idea(self, text: str, user_id: int) -> SavedIdea:
        """Extract tags and classify complexity/effort with Claude, persist Item + Idea."""
        tags, complexity, effort = await self._analyse(text)
        item = await self._item_repo.create(user_id=user_id, type=ItemType.idea, content=text)
        idea = await self._idea_repo.save(
            item_id=item.id, tags=tags, complexity=complexity, effort=effort
        )
        await self._session.commit()
        return SavedIdea(item=item, idea=idea)

    async def suggest(self, user_id: int, query: str) -> str:
        """Return Claude suggestions based on saved ideas; user-friendly fallback on error."""
        rows = await self._idea_repo.get_all(user_id)
        if not rows:
            return "У тебя пока нет сохранённых идей. Поделись идеей — просто напиши её!"

        ideas_text = "\n".join(
            f"- {item.content} [теги: {', '.join(idea.tags)}]" if idea.tags else f"- {item.content}"
            for item, idea in rows
        )
        prompt = _SUGGEST_PROMPT.format(ideas=ideas_text, query=query)
        try:
            return await self._claude.complete(prompt, max_tokens=512)
        except Exception:
            logger.exception("Idea suggestion failed")
            return "Не удалось сгенерировать подсказку. Попробуй ещё раз."

    async def get_all(self, user_id: int) -> list[tuple[Item, Idea]]:
        """Return all (Item, Idea) pairs for user, newest first."""
        return await self._idea_repo.get_all(user_id)

    async def _analyse(
        self, text: str
    ) -> tuple[list[str], IdeaComplexity | None, IdeaEffort | None]:
        """Extract tags and estimate complexity/effort concurrently; return defaults on failure."""
        import asyncio

        tags_coro = self._extract_tags(text)
        classify_coro = self._classify_complexity(text)
        tags, (complexity, effort) = await asyncio.gather(tags_coro, classify_coro)
        return tags, complexity, effort

    async def _extract_tags(self, text: str) -> list[str]:
        """Call Claude to extract tags from idea text; return empty list on failure."""
        try:
            response = await self._claude.complete(_TAG_PROMPT + text)
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
                cleaned = cleaned.strip()
            tags = json.loads(cleaned)
            if isinstance(tags, list):
                return [str(t).lower()[:30] for t in tags[:5]]
        except Exception:
            logger.exception("Tag extraction failed, saving idea without tags")
        return []

    async def _classify_complexity(
        self, text: str
    ) -> tuple[IdeaComplexity | None, IdeaEffort | None]:
        """Call Claude to estimate complexity and effort; return (None, None) on failure."""
        try:
            response = await self._claude.complete(_CLASSIFY_PROMPT + text)
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
                cleaned = cleaned.strip()
            data = json.loads(cleaned)
            complexity = _COMPLEXITY_MAP.get(data.get("complexity", ""))
            effort = _EFFORT_MAP.get(data.get("effort", ""))
            return complexity, effort
        except Exception:
            logger.exception("Complexity classification failed, saving without complexity")
            return None, None
