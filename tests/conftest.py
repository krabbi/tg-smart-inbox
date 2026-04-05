import pytest

from bot.config import Config


@pytest.fixture
def fake_config() -> Config:
    return Config(
        telegram_bot_token="1234567890:AAFakeTokenForTestingPurposesOnly",
        anthropic_api_key="sk-ant-fake-key-for-testing",
        database_url="sqlite+aiosqlite:///data/test.db",
        allowed_user_ids=[123456789],
    )
