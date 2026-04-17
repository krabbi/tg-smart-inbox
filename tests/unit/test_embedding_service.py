import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from bot.config import Config
from bot.models.idea import Idea
from bot.models.item import Item, ItemType
from bot.services.embedding_service import EmbeddingService


def make_config(embedding_dim: int = 4) -> Config:
    return Config(
        telegram_bot_token="fake",
        anthropic_api_key="sk-ant-fake",
        embedding_dim=embedding_dim,
    )


def make_item(
    *,
    content: str = "Hello world",
    description: str | None = None,
    scraped_text: str | None = None,
    item_type: ItemType = ItemType.note,
) -> Item:
    item = MagicMock(spec=Item)
    item.id = uuid.uuid4()
    item.user_id = 1
    item.type = item_type
    item.content = content
    item.description = description
    item.scraped_text = scraped_text
    return item


def make_idea(
    *,
    tags: list[str] | None = None,
    parent_content: str = "The idea content",
) -> Idea:
    idea = MagicMock(spec=Idea)
    idea.id = uuid.uuid4()
    idea.tags = tags if tags is not None else []
    idea.item = make_item(content=parent_content)
    return idea


# ─── generate ────────────────────────────────────────────────────────────────


async def test_generate_returns_vector_on_success() -> None:
    svc = EmbeddingService(make_config(embedding_dim=4))
    response = {"data": [{"embedding": [0.1, 0.2, 0.3, 0.4]}]}

    with patch.object(svc._client, "post", new=AsyncMock(return_value=response)):
        vector = await svc.generate("hello")

    assert vector == [0.1, 0.2, 0.3, 0.4]


async def test_generate_returns_none_on_api_error() -> None:
    svc = EmbeddingService(make_config())

    with patch.object(svc._client, "post", new=AsyncMock(side_effect=Exception("boom"))):
        result = await svc.generate("hello")

    assert result is None


async def test_generate_returns_none_for_empty_text() -> None:
    svc = EmbeddingService(make_config())
    # Whitespace-only input must short-circuit without hitting the API.
    with patch.object(svc._client, "post", new=AsyncMock()) as mock_post:
        result = await svc.generate("   ")
    assert result is None
    mock_post.assert_not_awaited()


async def test_generate_returns_none_when_response_missing_vector() -> None:
    svc = EmbeddingService(make_config())

    with patch.object(svc._client, "post", new=AsyncMock(return_value={"data": []})):
        result = await svc.generate("hello")

    assert result is None


async def test_generate_returns_none_when_vector_wrong_dimension() -> None:
    # dim in config is 4 but we receive 3 floats
    svc = EmbeddingService(make_config(embedding_dim=4))
    response = {"data": [{"embedding": [0.1, 0.2, 0.3]}]}

    with patch.object(svc._client, "post", new=AsyncMock(return_value=response)):
        result = await svc.generate("hello")

    assert result is None


async def test_generate_truncates_long_input() -> None:
    svc = EmbeddingService(make_config())
    long_text = "a" * 20000
    response = {"data": [{"embedding": [0.0, 0.1, 0.2, 0.3]}]}

    with patch.object(svc._client, "post", new=AsyncMock(return_value=response)) as mock_post:
        await svc.generate(long_text)

    sent = mock_post.await_args.kwargs["body"]
    assert len(sent["input"]) <= 8000


async def test_generate_accepts_top_level_embedding_shape() -> None:
    """Graceful parsing: accept `{"embedding": [...]}` as well as the `data` list shape."""
    svc = EmbeddingService(make_config(embedding_dim=4))
    response = {"embedding": [1.0, 2.0, 3.0, 4.0]}

    with patch.object(svc._client, "post", new=AsyncMock(return_value=response)):
        vector = await svc.generate("hello")

    assert vector == [1.0, 2.0, 3.0, 4.0]


async def test_generate_returns_none_for_non_list_vector() -> None:
    svc = EmbeddingService(make_config())
    response = {"data": [{"embedding": "not a list"}]}

    with patch.object(svc._client, "post", new=AsyncMock(return_value=response)):
        result = await svc.generate("hello")

    assert result is None


# ─── generate_for_item ───────────────────────────────────────────────────────


async def test_generate_for_item_uses_content_and_description() -> None:
    svc = EmbeddingService(make_config(embedding_dim=4))
    item = make_item(content="Buy milk", description="urgent", scraped_text=None)
    response = {"data": [{"embedding": [0.1, 0.2, 0.3, 0.4]}]}

    with patch.object(svc._client, "post", new=AsyncMock(return_value=response)) as mock_post:
        vector = await svc.generate_for_item(item)

    sent_text = mock_post.await_args.kwargs["body"]["input"]
    assert "Buy milk" in sent_text
    assert "urgent" in sent_text
    assert vector == [0.1, 0.2, 0.3, 0.4]


async def test_generate_for_item_includes_scraped_text() -> None:
    svc = EmbeddingService(make_config(embedding_dim=4))
    item = make_item(
        content="https://example.com",
        description="Example title",
        scraped_text="The page talks about X",
        item_type=ItemType.link,
    )
    response = {"data": [{"embedding": [0.1, 0.2, 0.3, 0.4]}]}

    with patch.object(svc._client, "post", new=AsyncMock(return_value=response)) as mock_post:
        await svc.generate_for_item(item)

    sent_text = mock_post.await_args.kwargs["body"]["input"]
    assert "The page talks about X" in sent_text


async def test_generate_for_item_returns_none_on_empty_item() -> None:
    svc = EmbeddingService(make_config())
    item = make_item(content="", description=None, scraped_text=None)

    with patch.object(svc._client, "post", new=AsyncMock()) as mock_post:
        result = await svc.generate_for_item(item)

    assert result is None
    mock_post.assert_not_awaited()


# ─── generate_for_idea ───────────────────────────────────────────────────────


async def test_generate_for_idea_includes_content_and_tags() -> None:
    svc = EmbeddingService(make_config(embedding_dim=4))
    idea = make_idea(tags=["mobile", "app"], parent_content="Build a mobile app")
    response = {"data": [{"embedding": [0.1, 0.2, 0.3, 0.4]}]}

    with patch.object(svc._client, "post", new=AsyncMock(return_value=response)) as mock_post:
        vector = await svc.generate_for_idea(idea)

    sent_text = mock_post.await_args.kwargs["body"]["input"]
    assert "Build a mobile app" in sent_text
    assert "mobile" in sent_text
    assert "app" in sent_text
    assert vector == [0.1, 0.2, 0.3, 0.4]


async def test_generate_for_idea_without_parent_item() -> None:
    """If the parent Item relationship is unset, tags alone are enough to embed."""
    svc = EmbeddingService(make_config(embedding_dim=4))
    idea = MagicMock(spec=Idea)
    idea.id = uuid.uuid4()
    idea.tags = ["creative"]
    idea.item = None
    response = {"data": [{"embedding": [0.1, 0.2, 0.3, 0.4]}]}

    with patch.object(svc._client, "post", new=AsyncMock(return_value=response)) as mock_post:
        vector = await svc.generate_for_idea(idea)

    sent_text = mock_post.await_args.kwargs["body"]["input"]
    assert "creative" in sent_text
    assert vector == [0.1, 0.2, 0.3, 0.4]


async def test_generate_for_idea_returns_none_on_empty_idea() -> None:
    svc = EmbeddingService(make_config())
    idea = MagicMock(spec=Idea)
    idea.id = uuid.uuid4()
    idea.tags = []
    idea.item = None

    with patch.object(svc._client, "post", new=AsyncMock()) as mock_post:
        result = await svc.generate_for_idea(idea)

    assert result is None
    mock_post.assert_not_awaited()
