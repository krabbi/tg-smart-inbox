import uuid
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.idea import Idea, IdeaComplexity, IdeaEffort
from bot.models.item import Item, ItemType
from bot.repositories.idea_repository import IdeaRepository
from bot.repositories.item_repository import ItemRepository
from bot.services.claude_client import ClaudeClient
from bot.services.embedding_service import EmbeddingService
from bot.services.idea_service import (
    _CLASSIFY_PROMPT,
    _SUGGEST_PROMPT,
    _TAG_PROMPT,
    IdeaService,
    IdeasPage,
    SavedIdea,
)

_DEFAULT_COMPLEXITY = '{"complexity": "simple", "effort": "quick"}'


def make_service(
    tag_response: str = '["app", "mobile"]',
    complexity_response: str = _DEFAULT_COMPLEXITY,
    suggest_response: str = "Вот идея: сделай приложение.",
    embedding: list[float] | None = None,
) -> tuple[IdeaService, MagicMock, MagicMock, MagicMock]:
    """Build IdeaService with all dependencies mocked.

    save_idea triggers two concurrent Claude calls (tags + complexity),
    so side_effect supplies tag_response and complexity_response first.
    """
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    mock_item = MagicMock(spec=Item)
    mock_item.id = uuid.uuid4()
    mock_item.type = ItemType.idea
    mock_item.content = "Build a mobile app"

    item_repo = MagicMock(spec=ItemRepository)
    item_repo.create = AsyncMock(return_value=mock_item)
    item_repo.update_embedding = AsyncMock()

    mock_idea = MagicMock(spec=Idea)
    mock_idea.id = uuid.uuid4()
    mock_idea.tags = ["app", "mobile"]
    mock_idea.complexity = IdeaComplexity.simple
    mock_idea.effort = IdeaEffort.quick

    idea_repo = MagicMock(spec=IdeaRepository)
    idea_repo.save = AsyncMock(return_value=mock_idea)
    idea_repo.get_all = AsyncMock(return_value=[])
    idea_repo.update_embedding = AsyncMock()

    claude = MagicMock(spec=ClaudeClient)
    # save_idea calls _extract_tags and _classify_complexity concurrently (asyncio.gather),
    # then suggest calls claude once more — order within gather is not guaranteed, but
    # side_effect list is consumed in call order which matches gather's task scheduling.
    claude.complete = AsyncMock(side_effect=[tag_response, complexity_response, suggest_response])

    embedding_service = MagicMock(spec=EmbeddingService)
    embedding_service.generate_for_item = AsyncMock(return_value=embedding)
    embedding_service.generate_for_idea = AsyncMock(return_value=embedding)

    svc = IdeaService(
        session=session,
        item_repo=item_repo,
        idea_repo=idea_repo,
        claude=claude,
        embedding_service=embedding_service,
    )
    return svc, item_repo, idea_repo, claude


async def test_save_idea_extracts_tags_and_saves() -> None:
    svc, item_repo, idea_repo, claude = make_service()

    result = await svc.save_idea("Build a mobile app", user_id=1)

    assert isinstance(result, SavedIdea)
    item_repo.create.assert_awaited_once_with(
        user_id=1, type=ItemType.idea, content="Build a mobile app"
    )
    idea_repo.save.assert_awaited_once()
    assert result.idea.tags == ["app", "mobile"]


async def test_save_idea_commits_session() -> None:
    svc, _, _, _ = make_service()
    await svc.save_idea("test idea", user_id=42)
    # Base save commits once; indexing adds another commit when successful.
    assert svc._session.commit.await_count >= 1


async def test_save_idea_marks_indexed_when_both_vectors_succeed() -> None:
    svc, item_repo, idea_repo, _ = make_service(embedding=[0.1] * 1024)
    saved = await svc.save_idea("idea", user_id=1)
    assert saved.indexed is True
    item_repo.update_embedding.assert_awaited_once()
    idea_repo.update_embedding.assert_awaited_once()


async def test_save_idea_not_indexed_when_embedding_none() -> None:
    svc, _, _, _ = make_service(embedding=None)
    saved = await svc.save_idea("idea", user_id=1)
    assert saved.indexed is False


async def test_save_idea_not_indexed_when_embedding_raises() -> None:
    svc, _, _, _ = make_service()
    svc._embedding.generate_for_item = AsyncMock(side_effect=Exception("API down"))  # type: ignore[attr-defined, union-attr]
    saved = await svc.save_idea("idea", user_id=1)
    assert saved.indexed is False


async def test_save_idea_not_indexed_without_embedding_service() -> None:
    """Without an EmbeddingService the idea still saves but indexing is skipped."""
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    item_repo = MagicMock(spec=ItemRepository)
    mock_item = MagicMock(spec=Item)
    mock_item.id = uuid.uuid4()
    mock_item.content = "idea"
    item_repo.create = AsyncMock(return_value=mock_item)
    mock_idea = MagicMock(spec=Idea)
    mock_idea.tags = []
    mock_idea.complexity = None
    mock_idea.effort = None
    idea_repo = MagicMock(spec=IdeaRepository)
    idea_repo.save = AsyncMock(return_value=mock_idea)
    claude = MagicMock(spec=ClaudeClient)
    claude.complete = AsyncMock(side_effect=["[]", '{"complexity": "simple", "effort": "quick"}'])

    svc = IdeaService(
        session=session,
        item_repo=item_repo,
        idea_repo=idea_repo,
        claude=claude,
        embedding_service=None,
    )
    saved = await svc.save_idea("idea", user_id=1)
    assert saved.indexed is False


async def test_save_idea_rolls_back_on_update_embedding_error() -> None:
    svc, item_repo, _, _ = make_service(embedding=[0.1] * 1024)
    item_repo.update_embedding = AsyncMock(side_effect=Exception("DB blew up"))

    saved = await svc.save_idea("idea", user_id=1)

    assert saved.indexed is False
    svc._session.rollback.assert_awaited_once()


async def test_save_idea_empty_tags_on_malformed_json() -> None:
    svc, _, idea_repo, _ = make_service(tag_response="not json")
    await svc.save_idea("some idea", user_id=1)
    assert idea_repo.save.call_args[1]["tags"] == []


async def test_save_idea_empty_tags_on_api_error() -> None:
    svc, _, idea_repo, claude = make_service()
    claude.complete = AsyncMock(side_effect=Exception("API down"))
    await svc.save_idea("some idea", user_id=1)
    call_kwargs = idea_repo.save.call_args[1]
    assert call_kwargs["tags"] == []


async def test_save_idea_passes_complexity_and_effort_to_repo() -> None:
    svc, _, idea_repo, _ = make_service(
        complexity_response='{"complexity": "complex", "effort": "longterm"}'
    )
    await svc.save_idea("build a helicopter", user_id=1)
    call_kwargs = idea_repo.save.call_args[1]
    assert call_kwargs["complexity"] == IdeaComplexity.complex
    assert call_kwargs["effort"] == IdeaEffort.longterm


async def test_save_idea_handles_unknown_complexity_values() -> None:
    svc, _, idea_repo, _ = make_service(
        complexity_response='{"complexity": "unknown", "effort": "unknown"}'
    )
    await svc.save_idea("some idea", user_id=1)
    call_kwargs = idea_repo.save.call_args[1]
    assert call_kwargs["complexity"] is None
    assert call_kwargs["effort"] is None


async def test_save_idea_complexity_on_api_error_defaults_to_none() -> None:
    svc, _, idea_repo, claude = make_service()
    # Both concurrent calls fail
    claude.complete = AsyncMock(side_effect=Exception("API down"))
    await svc.save_idea("some idea", user_id=1)
    call_kwargs = idea_repo.save.call_args[1]
    assert call_kwargs["complexity"] is None
    assert call_kwargs["effort"] is None


async def test_classify_complexity_strips_markdown_fence() -> None:
    svc, _, _, claude = make_service()
    claude.complete = AsyncMock(
        return_value='```json\n{"complexity": "medium", "effort": "halfday"}\n```'
    )
    complexity, effort = await svc._classify_complexity("do something")
    assert complexity == IdeaComplexity.medium
    assert effort == IdeaEffort.halfday


async def test_suggest_returns_claude_response() -> None:
    svc, _, idea_repo, claude = make_service(suggest_response="Попробуй сделать приложение!")
    idea_repo.get_all = AsyncMock(
        return_value=[
            (MagicMock(content="Build app", spec=Item), MagicMock(tags=["app"], spec=Idea))
        ]
    )
    claude.complete = AsyncMock(return_value="Попробуй сделать приложение!")

    result = await svc.suggest(user_id=1, query="что поделать?")
    assert "приложение" in result


async def test_suggest_empty_list_returns_friendly_message() -> None:
    svc, _, idea_repo, _ = make_service()
    idea_repo.get_all = AsyncMock(return_value=[])

    result = await svc.suggest(user_id=1, query="чем заняться?")
    assert "нет" in result.lower() or "идей" in result.lower()


async def test_suggest_api_error_returns_fallback() -> None:
    svc, _, idea_repo, claude = make_service()
    idea_repo.get_all = AsyncMock(
        return_value=[(MagicMock(content="idea", spec=Item), MagicMock(tags=[], spec=Idea))]
    )
    claude.complete = AsyncMock(side_effect=Exception("API error"))

    result = await svc.suggest(user_id=1, query="что делать?")
    assert "Не удалось" in result


async def test_get_all_delegates_to_repo() -> None:
    svc, _, idea_repo, _ = make_service()
    idea_repo.get_all = AsyncMock(return_value=["row1", "row2"])

    result = await svc.get_all(user_id=5)
    assert result == ["row1", "row2"]
    idea_repo.get_all.assert_awaited_once_with(5)


async def test_extract_tags_limits_to_five() -> None:
    svc, _, _, claude = make_service()
    claude.complete = AsyncMock(return_value='["a","b","c","d","e","f","g"]')

    tags = await svc._extract_tags("many tags idea")
    assert len(tags) == 5


async def test_extract_tags_lowercases() -> None:
    svc, _, _, claude = make_service()
    claude.complete = AsyncMock(return_value='["Mobile", "APP"]')

    tags = await svc._extract_tags("test")
    assert tags == ["mobile", "app"]


async def test_get_page_returns_ideas_page() -> None:
    svc, _, idea_repo, _ = make_service()
    idea_repo.count_by_user = AsyncMock(return_value=25)
    idea_repo.get_page = AsyncMock(return_value=[("row1", "idea1"), ("row2", "idea2")])

    result = await svc.get_page(user_id=1, page=1)

    assert isinstance(result, IdeasPage)
    assert result.page == 1
    assert result.total == 25
    assert len(result.rows) == 2
    idea_repo.count_by_user.assert_awaited_once_with(1)
    idea_repo.get_page.assert_awaited_once_with(1, limit=10, offset=10)


async def test_get_page_first_page_defaults() -> None:
    svc, _, idea_repo, _ = make_service()
    idea_repo.count_by_user = AsyncMock(return_value=5)
    idea_repo.get_page = AsyncMock(return_value=[])

    result = await svc.get_page(user_id=1)

    assert result.page == 0
    idea_repo.get_page.assert_awaited_once_with(1, limit=10, offset=0)


async def test_ideas_page_has_prev_and_has_next() -> None:
    page = IdeasPage(rows=[], page=0, total=5)
    assert not page.has_prev
    assert not page.has_next

    page = IdeasPage(rows=[], page=0, total=15)
    assert not page.has_prev
    assert page.has_next

    page = IdeasPage(rows=[], page=1, total=15)
    assert page.has_prev
    assert not page.has_next

    page = IdeasPage(rows=[], page=1, total=30)
    assert page.has_prev
    assert page.has_next


# ── Language propagation ─────────────────────────────────────────────────────


async def test_prompt_templates_are_language_neutral() -> None:
    """All three IdeaService prompts must reference ``{language}`` and not hardcode Russian."""
    for template in (_TAG_PROMPT, _CLASSIFY_PROMPT, _SUGGEST_PROMPT):
        assert "{language}" in template
        assert "Russian" not in template


async def test_save_idea_forwards_russian_into_both_prompts() -> None:
    """lang='ru' must surface as 'Russian' in tag-extraction and complexity prompts."""
    svc, _, _, claude = make_service()
    await svc.save_idea("купить вертолёт", user_id=1, lang="ru")

    # Two prompts are sent concurrently (tags + complexity); both must carry 'Russian'.
    sent_prompts = [call.args[0] for call in claude.complete.await_args_list]
    assert len(sent_prompts) == 2
    for prompt in sent_prompts:
        assert "Russian" in prompt
        assert "English" not in prompt


async def test_save_idea_forwards_english_into_both_prompts() -> None:
    """lang='en' must surface as 'English' in tag-extraction and complexity prompts."""
    svc, _, _, claude = make_service()
    await svc.save_idea("buy a helicopter", user_id=1, lang="en")

    sent_prompts = [call.args[0] for call in claude.complete.await_args_list]
    assert len(sent_prompts) == 2
    for prompt in sent_prompts:
        assert "English" in prompt
        assert "Russian" not in prompt


async def test_save_idea_default_lang_is_english() -> None:
    """Omitting lang on save_idea defaults to English in the Claude prompts."""
    svc, _, _, claude = make_service()
    await svc.save_idea("some idea", user_id=1)

    sent_prompts = [call.args[0] for call in claude.complete.await_args_list]
    for prompt in sent_prompts:
        assert "English" in prompt
        assert "Russian" not in prompt


async def test_suggest_forwards_russian_into_prompt() -> None:
    """lang='ru' must interpolate into the suggest prompt."""
    svc, _, idea_repo, claude = make_service()
    idea_repo.get_all = AsyncMock(
        return_value=[(MagicMock(content="idea", spec=Item), MagicMock(tags=[], spec=Idea))]
    )
    claude.complete = AsyncMock(return_value="Вот что можно сделать.")

    await svc.suggest(user_id=1, query="что поделать?", lang="ru")

    sent_prompt = claude.complete.await_args.args[0]
    assert "Russian" in sent_prompt
    assert "English" not in sent_prompt


async def test_suggest_forwards_english_into_prompt() -> None:
    """lang='en' must interpolate into the suggest prompt."""
    svc, _, idea_repo, claude = make_service()
    idea_repo.get_all = AsyncMock(
        return_value=[(MagicMock(content="idea", spec=Item), MagicMock(tags=[], spec=Idea))]
    )
    claude.complete = AsyncMock(return_value="Here's what to do.")

    await svc.suggest(user_id=1, query="what should I do?", lang="en")

    sent_prompt = claude.complete.await_args.args[0]
    assert "English" in sent_prompt
    assert "Russian" not in sent_prompt


async def test_suggest_default_lang_is_english() -> None:
    """Omitting lang on suggest defaults to English in the prompt."""
    svc, _, idea_repo, claude = make_service()
    idea_repo.get_all = AsyncMock(
        return_value=[(MagicMock(content="idea", spec=Item), MagicMock(tags=[], spec=Idea))]
    )
    claude.complete = AsyncMock(return_value="Here's what to do.")

    await svc.suggest(user_id=1, query="what should I do?")

    sent_prompt = claude.complete.await_args.args[0]
    assert "English" in sent_prompt
    assert "Russian" not in sent_prompt
