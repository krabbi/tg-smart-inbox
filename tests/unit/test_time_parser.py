from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.exceptions import TimeParseError
from bot.services.claude_client import ClaudeClient
from bot.services.time_parser import TimeParser

NOW = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)


def make_parser(response: str) -> TimeParser:
    client = MagicMock(spec=ClaudeClient)
    client.complete = AsyncMock(return_value=response)
    return TimeParser(client)


async def test_parse_tomorrow_at_10() -> None:
    parser = make_parser('{"datetime": "2026-06-02T10:00:00"}')
    result = await parser.parse("завтра в 10", now=NOW)
    assert result == datetime(2026, 6, 2, 10, 0)


async def test_parse_in_2_hours() -> None:
    parser = make_parser('{"datetime": "2026-06-01T10:00:00"}')
    result = await parser.parse("через 2 часа", now=NOW)
    assert result == datetime(2026, 6, 1, 10, 0)


async def test_unparseable_raises_time_parse_error() -> None:
    parser = make_parser('{"error": "unparseable"}')
    with pytest.raises(TimeParseError, match="Cannot parse time"):
        await parser.parse("абракадабра", now=NOW)


async def test_malformed_json_raises_time_parse_error() -> None:
    parser = make_parser("not json at all")
    with pytest.raises(TimeParseError, match="Malformed time response"):
        await parser.parse("завтра", now=NOW)


async def test_missing_datetime_field_raises_time_parse_error() -> None:
    parser = make_parser('{"result": "2026-06-02T10:00:00"}')
    with pytest.raises(TimeParseError):
        await parser.parse("завтра", now=NOW)


async def test_invalid_iso_format_raises_time_parse_error() -> None:
    parser = make_parser('{"datetime": "not-a-date"}')
    with pytest.raises(TimeParseError):
        await parser.parse("завтра", now=NOW)


async def test_claude_api_error_raises_time_parse_error() -> None:
    client = MagicMock(spec=ClaudeClient)
    client.complete = AsyncMock(side_effect=Exception("API down"))
    parser = TimeParser(client)
    with pytest.raises(TimeParseError, match="Time parsing failed"):
        await parser.parse("завтра", now=NOW)
