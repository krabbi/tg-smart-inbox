from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.config import Config
from bot.middleware import DependencyMiddleware


def make_session_factory(session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    """Create a mock session factory that yields the given session."""
    factory = MagicMock(spec=async_sessionmaker)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    factory.return_value = cm
    return factory


async def test_middleware_injects_session_and_config(fake_config: Config) -> None:
    session = MagicMock(spec=AsyncSession)
    factory = make_session_factory(session)
    middleware = DependencyMiddleware(factory, fake_config)

    captured: dict = {}

    async def handler(event: object, data: dict) -> str:
        captured.update(data)
        return "ok"

    result = await middleware(handler, MagicMock(), {})

    assert result == "ok"
    assert captured["session"] is session
    assert captured["config"] is fake_config


async def test_middleware_calls_handler_with_event(fake_config: Config) -> None:
    session = MagicMock(spec=AsyncSession)
    factory = make_session_factory(session)
    middleware = DependencyMiddleware(factory, fake_config)
    handler = AsyncMock(return_value="done")
    event = MagicMock()

    result = await middleware(handler, event, {})

    handler.assert_awaited_once()
    assert result == "done"


async def test_middleware_opens_session_per_call(fake_config: Config) -> None:
    session = MagicMock(spec=AsyncSession)
    factory = make_session_factory(session)
    middleware = DependencyMiddleware(factory, fake_config)
    handler = AsyncMock(return_value=None)

    await middleware(handler, MagicMock(), {})
    await middleware(handler, MagicMock(), {})

    assert factory.call_count == 2


async def test_middleware_injects_user_settings_service(fake_config: Config) -> None:
    from bot.services.user_settings_service import UserSettingsService

    session = MagicMock(spec=AsyncSession)
    factory = make_session_factory(session)
    middleware = DependencyMiddleware(factory, fake_config)

    captured: dict = {}

    async def handler(event: object, data: dict) -> None:
        captured.update(data)

    await middleware(handler, MagicMock(), {})

    assert isinstance(captured["user_settings_service"], UserSettingsService)


async def test_middleware_injects_embedding_service(fake_config: Config) -> None:
    from bot.services.embedding_service import EmbeddingService

    session = MagicMock(spec=AsyncSession)
    factory = make_session_factory(session)
    middleware = DependencyMiddleware(factory, fake_config)

    captured: dict = {}

    async def handler(event: object, data: dict) -> None:
        captured.update(data)

    await middleware(handler, MagicMock(), {})

    assert isinstance(captured["embedding_service"], EmbeddingService)


async def test_middleware_injects_semantic_search_service(fake_config: Config) -> None:
    from bot.services.semantic_search_service import SemanticSearchService

    session = MagicMock(spec=AsyncSession)
    factory = make_session_factory(session)
    middleware = DependencyMiddleware(factory, fake_config)

    captured: dict = {}

    async def handler(event: object, data: dict) -> None:
        captured.update(data)

    await middleware(handler, MagicMock(), {})

    assert isinstance(captured["semantic_search_service"], SemanticSearchService)


async def test_middleware_injects_reindex_service(fake_config: Config) -> None:
    from bot.services.reindex_service import ReindexService

    session = MagicMock(spec=AsyncSession)
    factory = make_session_factory(session)
    middleware = DependencyMiddleware(factory, fake_config)

    captured: dict = {}

    async def handler(event: object, data: dict) -> None:
        captured.update(data)

    await middleware(handler, MagicMock(), {})

    assert isinstance(captured["reindex_service"], ReindexService)
