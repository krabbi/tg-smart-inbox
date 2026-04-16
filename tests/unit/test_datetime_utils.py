"""Tests for bot.utils.datetime_utils.format_remind_at."""

from datetime import UTC, datetime

from bot.utils.datetime_utils import format_remind_at


def test_format_utc_keeps_time_and_uses_utc_label() -> None:
    """A UTC datetime stays in place and is labelled 'UTC'."""
    dt = datetime(2026, 4, 7, 13, 0, tzinfo=UTC)
    assert format_remind_at(dt, "UTC") == "07.04.2026 13:00 UTC"


def test_format_utc_naive_treated_as_utc() -> None:
    """A naive datetime is treated as UTC (legacy contract)."""
    dt = datetime(2026, 4, 7, 13, 0)
    assert format_remind_at(dt, "UTC") == "07.04.2026 13:00 UTC"


def test_format_moscow_converts_to_local_with_msk_abbreviation() -> None:
    """Europe/Moscow zone shifts UTC by +3h and uses the 'MSK' abbreviation."""
    dt = datetime(2026, 4, 7, 10, 0, tzinfo=UTC)
    assert format_remind_at(dt, "Europe/Moscow") == "07.04.2026 13:00 MSK"


def test_format_naive_input_with_non_utc_tz_treated_as_utc() -> None:
    """A naive input is treated as UTC even when displayed in a non-UTC zone."""
    dt = datetime(2026, 4, 7, 10, 0)  # naive — assumed UTC
    assert format_remind_at(dt, "Europe/Moscow") == "07.04.2026 13:00 MSK"


def test_format_new_york_dst_uses_edt_abbreviation() -> None:
    """A summer date in America/New_York is labelled with the DST abbreviation EDT."""
    dt = datetime(2026, 7, 15, 17, 0, tzinfo=UTC)  # 13:00 EDT (UTC−4)
    assert format_remind_at(dt, "America/New_York") == "15.07.2026 13:00 EDT"


def test_format_new_york_winter_uses_est_abbreviation() -> None:
    """A winter date in America/New_York is labelled with the standard abbreviation EST."""
    dt = datetime(2026, 1, 15, 18, 0, tzinfo=UTC)  # 13:00 EST (UTC−5)
    assert format_remind_at(dt, "America/New_York") == "15.01.2026 13:00 EST"


def test_format_kolkata_uses_ist_abbreviation() -> None:
    """Asia/Kolkata uses the alphabetic 'IST' abbreviation."""
    dt = datetime(2026, 4, 7, 7, 30, tzinfo=UTC)  # 13:00 IST (UTC+5:30)
    assert format_remind_at(dt, "Asia/Kolkata") == "07.04.2026 13:00 IST"


def test_format_zone_without_alpha_abbreviation_falls_back_to_iana_name() -> None:
    """Zones whose tzname is a numeric offset use the IANA name instead."""
    # Asia/Kabul is UTC+04:30 with a numeric tzname like '+0430'.
    dt = datetime(2026, 4, 7, 8, 30, tzinfo=UTC)  # 13:00 in Kabul
    assert format_remind_at(dt, "Asia/Kabul") == "07.04.2026 13:00 Asia/Kabul"


def test_format_invalid_timezone_falls_back_to_utc() -> None:
    """An invalid IANA name silently falls back to UTC formatting."""
    dt = datetime(2026, 4, 7, 13, 0, tzinfo=UTC)
    assert format_remind_at(dt, "Not/AZone") == "07.04.2026 13:00 UTC"


def test_format_aware_input_in_other_zone_is_converted() -> None:
    """An aware datetime in a non-UTC zone is converted to the requested user_tz."""
    from zoneinfo import ZoneInfo

    # 13:00 in Moscow → 10:00 UTC → 12:00 in Berlin
    dt = datetime(2026, 4, 7, 13, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    assert format_remind_at(dt, "Europe/Berlin") == "07.04.2026 12:00 CEST"
