import pytest
from pydantic import ValidationError

from bot.config import Config


def test_config_valid(fake_config: Config) -> None:
    assert fake_config.telegram_bot_token == "1234567890:AAFakeTokenForTestingPurposesOnly"
    assert fake_config.anthropic_api_key == "sk-ant-fake-key-for-testing"
    assert fake_config.allowed_user_ids == [123456789]


def test_config_missing_token_raises() -> None:
    with pytest.raises(ValidationError):
        Config(anthropic_api_key="sk-ant-fake")  # type: ignore[call-arg]


def test_config_missing_anthropic_key_raises() -> None:
    with pytest.raises(ValidationError):
        Config(telegram_bot_token="fake-token")  # type: ignore[call-arg]


def test_config_parse_user_ids_from_string() -> None:
    config = Config(
        telegram_bot_token="fake-token",
        anthropic_api_key="sk-ant-fake",
        allowed_user_ids="111,222, 333",  # type: ignore[arg-type]
    )
    assert config.allowed_user_ids == [111, 222, 333]


def test_config_default_database_url(fake_config: Config) -> None:
    config = Config(
        telegram_bot_token="fake-token",
        anthropic_api_key="sk-ant-fake",
    )
    assert config.database_url == "sqlite+aiosqlite:///data/bot.db"


def test_config_default_empty_user_ids() -> None:
    config = Config(
        telegram_bot_token="fake-token",
        anthropic_api_key="sk-ant-fake",
    )
    assert config.allowed_user_ids == []
