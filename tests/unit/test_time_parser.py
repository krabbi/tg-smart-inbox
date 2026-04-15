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


async def test_parse_json_in_markdown_fence() -> None:
    """Claude sometimes wraps JSON in ```json ... ``` — must still parse."""
    parser = make_parser('```json\n{"datetime": "2026-06-02T10:00:00"}\n```')
    result = await parser.parse("завтра в 10", now=NOW)
    assert result == datetime(2026, 6, 2, 10, 0)


async def test_parse_json_in_plain_fence() -> None:
    """Claude sometimes wraps JSON in ``` ... ``` without language tag."""
    parser = make_parser('```\n{"datetime": "2026-06-02T10:00:00"}\n```')
    result = await parser.parse("завтра в 10", now=NOW)
    assert result == datetime(2026, 6, 2, 10, 0)


async def test_parse_in_10_minutes() -> None:
    parser = make_parser('{"datetime": "2026-06-01T08:10:00"}')
    result = await parser.parse("через 10 минут", now=NOW)
    assert result == datetime(2026, 6, 1, 8, 10)


async def test_parse_in_english() -> None:
    parser = make_parser('{"datetime": "2026-06-01T10:00:00"}')
    result = await parser.parse("in 2 hours", now=NOW)
    assert result == datetime(2026, 6, 1, 10, 0)


async def test_parse_in_1_minute() -> None:
    """Short interval «через 1 минуту» must parse correctly."""
    parser = make_parser('{"datetime": "2026-06-01T08:01:00"}')
    result = await parser.parse("через 1 минуту", now=NOW)
    assert result == datetime(2026, 6, 1, 8, 1)


async def test_parse_in_3_minutes() -> None:
    """Short interval «через 3 минуты» (genitive singular) must parse correctly."""
    parser = make_parser('{"datetime": "2026-06-01T08:03:00"}')
    result = await parser.parse("через 3 минуты", now=NOW)
    assert result == datetime(2026, 6, 1, 8, 3)


async def test_parse_in_30_seconds() -> None:
    """Very short interval «через 30 секунд» must parse correctly."""
    parser = make_parser('{"datetime": "2026-06-01T08:00:30"}')
    result = await parser.parse("через 30 секунд", now=NOW)
    assert result == datetime(2026, 6, 1, 8, 0, 30)


async def test_parse_time_in_past_raises_time_parse_error() -> None:
    """A datetime that is at or before now must raise TimeParseError."""
    parser = make_parser('{"datetime": "2026-06-01T07:59:00"}')
    with pytest.raises(TimeParseError, match="not in the future"):
        await parser.parse("вчера", now=NOW)


async def test_parse_strips_timezone_from_claude_response() -> None:
    """Claude sometimes returns timezone-aware ISO strings; result must be naive UTC."""
    parser = make_parser('{"datetime": "2026-06-01T08:03:00+00:00"}')
    result = await parser.parse("через 3 минуты", now=NOW)
    assert result == datetime(2026, 6, 1, 8, 3)
    assert result.tzinfo is None


# ── user_tz parameter ────────────────────────────────────────────────────────


async def test_parse_default_user_tz_is_utc_and_returns_naive() -> None:
    """Without user_tz the parser behaves exactly as before (naive UTC datetime)."""
    parser = make_parser('{"datetime": "2026-06-02T10:00:00"}')
    result = await parser.parse("завтра в 10", now=NOW)
    assert result == datetime(2026, 6, 2, 10, 0)
    assert result.tzinfo is None


async def test_parse_explicit_utc_returns_naive_datetime() -> None:
    """user_tz='UTC' is explicitly backward-compatible — still naive."""
    parser = make_parser('{"datetime": "2026-06-02T10:00:00"}')
    result = await parser.parse("завтра в 10", now=NOW, user_tz="UTC")
    assert result == datetime(2026, 6, 2, 10, 0)
    assert result.tzinfo is None


async def test_parse_moscow_tomorrow_10_returns_07_utc() -> None:
    """«Завтра в 10» in Europe/Moscow (UTC+3) → 07:00 UTC — acceptance criterion from #66."""
    # Claude sees "now" as Moscow local time and returns tomorrow 10:00 local.
    parser = make_parser('{"datetime": "2026-06-02T10:00:00"}')
    result = await parser.parse("завтра в 10", now=NOW, user_tz="Europe/Moscow")
    assert result == datetime(2026, 6, 2, 7, 0, tzinfo=UTC)
    assert result.tzinfo is not None


async def test_parse_moscow_passes_local_time_in_prompt() -> None:
    """Prompt sent to Claude contains ``now`` converted to the user's local timezone."""
    client = MagicMock(spec=ClaudeClient)
    client.complete = AsyncMock(return_value='{"datetime": "2026-06-02T10:00:00"}')
    parser = TimeParser(client)

    await parser.parse("завтра в 10", now=NOW, user_tz="Europe/Moscow")

    prompt = client.complete.call_args[0][0]
    # NOW is 2026-06-01T08:00 UTC → 11:00 Moscow (UTC+3)
    assert "2026-06-01T11:00:00" in prompt
    assert "Europe/Moscow" in prompt


async def test_parse_berlin_summer_time_returns_utc_minus_2() -> None:
    """Europe/Berlin in June is CEST (UTC+2): 12:00 Berlin → 10:00 UTC."""
    parser = make_parser('{"datetime": "2026-06-02T12:00:00"}')
    result = await parser.parse("завтра в 12", now=NOW, user_tz="Europe/Berlin")
    assert result == datetime(2026, 6, 2, 10, 0, tzinfo=UTC)


async def test_parse_berlin_winter_time_returns_utc_minus_1() -> None:
    """Europe/Berlin in January is CET (UTC+1): 12:00 Berlin → 11:00 UTC."""
    winter_now = datetime(2026, 1, 15, 8, 0, tzinfo=UTC)
    parser = make_parser('{"datetime": "2026-01-16T12:00:00"}')
    result = await parser.parse("завтра в 12", now=winter_now, user_tz="Europe/Berlin")
    assert result == datetime(2026, 1, 16, 11, 0, tzinfo=UTC)


async def test_parse_new_york_summer_time_returns_utc_plus_4() -> None:
    """America/New_York in June is EDT (UTC-4): 10:00 NY → 14:00 UTC."""
    parser = make_parser('{"datetime": "2026-06-02T10:00:00"}')
    result = await parser.parse("tomorrow at 10", now=NOW, user_tz="America/New_York")
    assert result == datetime(2026, 6, 2, 14, 0, tzinfo=UTC)


async def test_parse_new_york_winter_time_returns_utc_plus_5() -> None:
    """America/New_York in January is EST (UTC-5): 10:00 NY → 15:00 UTC."""
    winter_now = datetime(2026, 1, 15, 8, 0, tzinfo=UTC)
    parser = make_parser('{"datetime": "2026-01-16T10:00:00"}')
    result = await parser.parse("tomorrow at 10", now=winter_now, user_tz="America/New_York")
    assert result == datetime(2026, 1, 16, 15, 0, tzinfo=UTC)


async def test_parse_invalid_user_tz_falls_back_to_utc() -> None:
    """Invalid IANA name silently falls back to UTC (naive return)."""
    parser = make_parser('{"datetime": "2026-06-02T10:00:00"}')
    result = await parser.parse("завтра в 10", now=NOW, user_tz="Not/AReal_Zone")
    assert result == datetime(2026, 6, 2, 10, 0)
    assert result.tzinfo is None


async def test_parse_past_in_user_tz_raises_time_parse_error() -> None:
    """A parsed time in the past (after tz conversion) must still raise."""
    # NOW = 2026-06-01 08:00 UTC = 11:00 Moscow. A local 09:00 Moscow is in the past (06:00 UTC).
    parser = make_parser('{"datetime": "2026-06-01T09:00:00"}')
    with pytest.raises(TimeParseError, match="not in the future"):
        await parser.parse("сегодня в 9", now=NOW, user_tz="Europe/Moscow")


async def test_parse_moscow_strips_timezone_from_claude_response() -> None:
    """Claude-provided tzinfo is dropped and replaced with the user's tz before UTC convert."""
    # If Claude returns "+00:00", we still interpret naive datetime as Moscow-local.
    parser = make_parser('{"datetime": "2026-06-02T10:00:00+00:00"}')
    result = await parser.parse("завтра в 10", now=NOW, user_tz="Europe/Moscow")
    # 10:00 Moscow → 07:00 UTC (not 10:00 UTC)
    assert result == datetime(2026, 6, 2, 7, 0, tzinfo=UTC)
