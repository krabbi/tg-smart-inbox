import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from bot.config import Config
from bot.models.idea import Idea
from bot.models.item import Item, ItemType
from bot.services.embedding_service import EmbeddingService


def make_config(embedding_dim: int = 4) -> Config:
    return Config(
        telegram_bot_token="fake",
        anthropic_api_key="sk-ant-fake",
        voyage_api_key="pa-fake",
        embedding_dim=embedding_dim,
    )


def make_voyage_response(vector: list[float]) -> MagicMock:
    body = {"data": [{"embedding": vector, "index": 0}], "model": "voyage-3.5"}
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=body)
    return resp


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


def _patch_httpx(response: MagicMock) -> AsyncMock:
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=response)
    return mock_client


def _patch_httpx_sequence(responses: list[MagicMock]) -> AsyncMock:
    """Return a client whose ``.post`` yields each response in turn."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(side_effect=responses)
    return mock_client


def _make_status_response(status_code: int) -> MagicMock:
    """Build a response mock whose ``raise_for_status`` raises for non-2xx codes."""
    resp = MagicMock()
    resp.status_code = status_code
    request = httpx.Request("POST", "https://example.com")
    http_response = httpx.Response(status_code, request=request)
    resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(f"{status_code}", request=request, response=http_response)
    )
    resp.json = MagicMock(return_value={})
    return resp


# ─── generate ────────────────────────────────────────────────────────────────


async def test_generate_returns_vector_on_success() -> None:
    svc = EmbeddingService(make_config(embedding_dim=4))
    mock_client = _patch_httpx(make_voyage_response([0.1, 0.2, 0.3, 0.4]))

    with patch("bot.services.embedding_service.httpx.AsyncClient", return_value=mock_client):
        vector = await svc.generate("hello")

    assert vector == [0.1, 0.2, 0.3, 0.4]


async def test_generate_returns_none_on_api_error() -> None:
    svc = EmbeddingService(make_config())
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(side_effect=Exception("boom"))

    with patch("bot.services.embedding_service.httpx.AsyncClient", return_value=mock_client):
        result = await svc.generate("hello")

    assert result is None


async def test_generate_returns_none_for_empty_text() -> None:
    svc = EmbeddingService(make_config())
    mock_client = _patch_httpx(make_voyage_response([]))

    with patch("bot.services.embedding_service.httpx.AsyncClient", return_value=mock_client):
        result = await svc.generate("   ")

    assert result is None
    mock_client.post.assert_not_awaited()


async def test_generate_returns_none_when_no_api_key() -> None:
    cfg = Config(
        telegram_bot_token="fake",
        anthropic_api_key="sk-ant-fake",
        voyage_api_key="",
        embedding_dim=4,
    )
    svc = EmbeddingService(cfg)
    result = await svc.generate("hello")
    assert result is None


async def test_generate_returns_none_when_response_missing_vector() -> None:
    svc = EmbeddingService(make_config())
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"data": [], "model": "voyage-3.5"})
    mock_client = _patch_httpx(resp)

    with patch("bot.services.embedding_service.httpx.AsyncClient", return_value=mock_client):
        result = await svc.generate("hello")

    assert result is None


async def test_generate_returns_none_when_vector_wrong_dimension() -> None:
    svc = EmbeddingService(make_config(embedding_dim=4))
    mock_client = _patch_httpx(make_voyage_response([0.1, 0.2, 0.3]))

    with patch("bot.services.embedding_service.httpx.AsyncClient", return_value=mock_client):
        result = await svc.generate("hello")

    assert result is None


async def test_generate_truncates_long_input_via_payload() -> None:
    svc = EmbeddingService(make_config(embedding_dim=4))
    long_text = "a" * 20000
    mock_client = _patch_httpx(make_voyage_response([0.0, 0.1, 0.2, 0.3]))

    with patch("bot.services.embedding_service.httpx.AsyncClient", return_value=mock_client):
        await svc.generate(long_text)

    sent_input = mock_client.post.await_args.kwargs["json"]["input"][0]
    assert len(sent_input) <= 8000


async def test_generate_retries_after_429_then_returns_vector() -> None:
    """After a single 429 the service waits and retries, returning the vector on success."""
    svc = EmbeddingService(make_config(embedding_dim=4))
    rate_limited = _make_status_response(429)
    success = make_voyage_response([0.1, 0.2, 0.3, 0.4])
    mock_client = _patch_httpx_sequence([rate_limited, success])

    with (
        patch("bot.services.embedding_service.httpx.AsyncClient", return_value=mock_client),
        patch("bot.services.embedding_service.asyncio.sleep", new=AsyncMock()) as mock_sleep,
    ):
        vector = await svc.generate("hello")

    assert vector == [0.1, 0.2, 0.3, 0.4]
    assert mock_client.post.await_count == 2
    mock_sleep.assert_awaited_once()


async def test_generate_returns_none_after_all_429_retries_exhausted() -> None:
    """Three consecutive 429 responses exhaust the retry budget and yield ``None``."""
    svc = EmbeddingService(make_config(embedding_dim=4))
    responses = [_make_status_response(429) for _ in range(3)]
    mock_client = _patch_httpx_sequence(responses)

    with (
        patch("bot.services.embedding_service.httpx.AsyncClient", return_value=mock_client),
        patch("bot.services.embedding_service.asyncio.sleep", new=AsyncMock()) as mock_sleep,
    ):
        result = await svc.generate("hello")

    assert result is None
    assert mock_client.post.await_count == 3
    # Two retries means exactly two sleeps before the final failing attempt.
    assert mock_sleep.await_count == 2


async def test_generate_returns_none_on_non_429_http_error() -> None:
    """A 401 (bad key) must not trigger retries; the service logs and returns ``None``."""
    svc = EmbeddingService(make_config(embedding_dim=4))
    mock_client = _patch_httpx(_make_status_response(401))

    with (
        patch("bot.services.embedding_service.httpx.AsyncClient", return_value=mock_client),
        patch("bot.services.embedding_service.asyncio.sleep", new=AsyncMock()) as mock_sleep,
    ):
        result = await svc.generate("hello")

    assert result is None
    # No retry path — only a single request, no sleeps.
    assert mock_client.post.await_count == 1
    mock_sleep.assert_not_awaited()


# ─── generate_for_item ───────────────────────────────────────────────────────


async def test_generate_for_item_uses_content_and_description() -> None:
    svc = EmbeddingService(make_config(embedding_dim=4))
    item = make_item(content="Buy milk", description="urgent", scraped_text=None)
    mock_client = _patch_httpx(make_voyage_response([0.1, 0.2, 0.3, 0.4]))

    with patch("bot.services.embedding_service.httpx.AsyncClient", return_value=mock_client):
        vector = await svc.generate_for_item(item)

    sent_text = mock_client.post.await_args.kwargs["json"]["input"][0]
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
    mock_client = _patch_httpx(make_voyage_response([0.1, 0.2, 0.3, 0.4]))

    with patch("bot.services.embedding_service.httpx.AsyncClient", return_value=mock_client):
        await svc.generate_for_item(item)

    sent_text = mock_client.post.await_args.kwargs["json"]["input"][0]
    assert "The page talks about X" in sent_text


async def test_generate_for_item_returns_none_on_empty_item() -> None:
    svc = EmbeddingService(make_config())
    item = make_item(content="", description=None, scraped_text=None)
    mock_client = _patch_httpx(make_voyage_response([]))

    with patch("bot.services.embedding_service.httpx.AsyncClient", return_value=mock_client):
        result = await svc.generate_for_item(item)

    assert result is None
    mock_client.post.assert_not_awaited()


# ─── generate_for_idea ───────────────────────────────────────────────────────


async def test_generate_for_idea_includes_content_and_tags() -> None:
    svc = EmbeddingService(make_config(embedding_dim=4))
    idea = make_idea(tags=["mobile", "app"], parent_content="Build a mobile app")
    mock_client = _patch_httpx(make_voyage_response([0.1, 0.2, 0.3, 0.4]))

    with patch("bot.services.embedding_service.httpx.AsyncClient", return_value=mock_client):
        vector = await svc.generate_for_idea(idea)

    sent_text = mock_client.post.await_args.kwargs["json"]["input"][0]
    assert "Build a mobile app" in sent_text
    assert "mobile" in sent_text
    assert "app" in sent_text
    assert vector == [0.1, 0.2, 0.3, 0.4]


async def test_generate_for_idea_without_parent_item() -> None:
    svc = EmbeddingService(make_config(embedding_dim=4))
    idea = MagicMock(spec=Idea)
    idea.id = uuid.uuid4()
    idea.tags = ["creative"]
    idea.item = None
    mock_client = _patch_httpx(make_voyage_response([0.1, 0.2, 0.3, 0.4]))

    with patch("bot.services.embedding_service.httpx.AsyncClient", return_value=mock_client):
        vector = await svc.generate_for_idea(idea)

    sent_text = mock_client.post.await_args.kwargs["json"]["input"][0]
    assert "creative" in sent_text
    assert vector == [0.1, 0.2, 0.3, 0.4]


async def test_generate_for_idea_returns_none_on_empty_idea() -> None:
    svc = EmbeddingService(make_config())
    idea = MagicMock(spec=Idea)
    idea.id = uuid.uuid4()
    idea.tags = []
    idea.item = None
    mock_client = _patch_httpx(make_voyage_response([]))

    with patch("bot.services.embedding_service.httpx.AsyncClient", return_value=mock_client):
        result = await svc.generate_for_idea(idea)

    assert result is None
    mock_client.post.assert_not_awaited()
