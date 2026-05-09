"""Unit tests for the timezone setup FSM handler."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from bot.exceptions import InvalidTimezoneError
from bot.handlers.timezone_setup import (
    _CB_BACK_CONTINENT,
    _CB_BACK_COUNTRY,
    _CB_CONTINENT,
    _CB_COUNTRY,
    _CB_ZONE,
    _CONTINENT_COUNTRIES,
    _COUNTRY_LABELS,
    _STATE_CONTINENT_KEY,
    _STATE_COUNTRY_KEY,
    CONTINENT_ASIA,
    CONTINENT_EUROPE,
    CONTINENT_OTHER,
    TimezoneSetupStates,
    _continent_keyboard,
    _countries_with_zones,
    _country_keyboard,
    _country_label,
    _format_utc_offset,
    _zone_keyboard,
    _zone_label,
    cb_back_to_continent,
    cb_back_to_country,
    cb_pick_continent,
    cb_pick_country,
    cb_pick_zone,
    start_timezone_setup,
)
from bot.services.user_settings_service import UserSettingsService

# ── Helpers ──────────────────────────────────────────────────────────────────


def make_message(user_id: int = 123) -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.from_user = MagicMock(spec=User)
    msg.from_user.id = user_id
    msg.answer = AsyncMock()
    return msg


def make_callback(data: str, user_id: int = 123) -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.data = data
    cb.answer = AsyncMock()
    cb.from_user = MagicMock(spec=User)
    cb.from_user.id = user_id
    cb.message = MagicMock(spec=Message)
    cb.message.edit_text = AsyncMock()
    cb.message.answer = AsyncMock()
    return cb


def make_state(initial_data: dict | None = None) -> MagicMock:
    state = MagicMock(spec=FSMContext)
    store: dict = dict(initial_data or {})

    async def get_data() -> dict:
        return dict(store)

    async def update_data(new: dict) -> None:
        store.update(new)

    state.get_data = AsyncMock(side_effect=get_data)
    state.update_data = AsyncMock(side_effect=update_data)
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    return state


def make_tz_service() -> MagicMock:
    svc = MagicMock(spec=UserSettingsService)
    svc.set_timezone = AsyncMock()
    svc.has_timezone = AsyncMock(return_value=False)
    return svc


# ── Pure helpers ─────────────────────────────────────────────────────────────


def test_continent_keyboard_has_four_options() -> None:
    kb = _continent_keyboard("ru")
    flat = [b.text for row in kb.inline_keyboard for b in row]
    assert "Европа" in flat
    assert "Азия" in flat
    assert "Америка" in flat
    assert "Другое" in flat


def test_continent_keyboard_localizes_labels_en() -> None:
    kb = _continent_keyboard("en")
    flat = [b.text for row in kb.inline_keyboard for b in row]
    assert "Europe" in flat
    assert "Asia" in flat
    assert "America" in flat
    assert "Other" in flat


def test_country_keyboard_has_back_button() -> None:
    kb, pairs = _country_keyboard(CONTINENT_EUROPE, "ru")
    assert len(pairs) > 0
    # last row has a single back button
    last_row = kb.inline_keyboard[-1]
    assert len(last_row) == 1
    assert "Назад" in last_row[0].text
    assert last_row[0].callback_data == _CB_BACK_CONTINENT


def test_country_keyboard_labels_are_localized_ru() -> None:
    kb, pairs = _country_keyboard(CONTINENT_OTHER, "ru")
    expected = {_country_label(slug, "ru") for slug, _ in pairs}
    labels = {b.text for row in kb.inline_keyboard[:-1] for b in row}
    assert labels == expected
    # Sanity check: at least one well-known country renders in Russian.
    assert "Австралия" in labels


def test_country_keyboard_labels_are_localized_en() -> None:
    kb, pairs = _country_keyboard(CONTINENT_OTHER, "en")
    expected = {_country_label(slug, "en") for slug, _ in pairs}
    labels = {b.text for row in kb.inline_keyboard[:-1] for b in row}
    assert labels == expected
    # Sanity check: at least one well-known country renders in English.
    assert "Australia" in labels
    assert "Австралия" not in labels


def test_country_keyboard_europe_localizes_russia_and_germany() -> None:
    kb_ru, _ = _country_keyboard(CONTINENT_EUROPE, "ru")
    kb_en, _ = _country_keyboard(CONTINENT_EUROPE, "en")
    labels_ru = {b.text for row in kb_ru.inline_keyboard[:-1] for b in row}
    labels_en = {b.text for row in kb_en.inline_keyboard[:-1] for b in row}
    assert "Россия" in labels_ru
    assert "Германия" in labels_ru
    assert "Russia" in labels_en
    assert "Germany" in labels_en
    # No leakage across languages.
    assert "Россия" not in labels_en
    assert "Russia" not in labels_ru


def test_zone_keyboard_has_back_button() -> None:
    kb = _zone_keyboard(["Europe/Moscow", "Asia/Yekaterinburg"], "ru")
    last_row = kb.inline_keyboard[-1]
    assert last_row[0].callback_data == _CB_BACK_COUNTRY


def test_zone_label_strips_prefix_and_underscores() -> None:
    assert _zone_label("Europe/Moscow") == "Moscow"
    assert _zone_label("America/New_York") == "New York"
    assert _zone_label("America/Argentina/Buenos_Aires") == "Buenos Aires"
    assert _zone_label("UTC") == "UTC"


def test_format_utc_offset_positive() -> None:
    # Force a known moment to avoid DST surprises
    moment = datetime(2026, 1, 15, 12, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    assert _format_utc_offset("Europe/Moscow", now=moment) == "UTC+03:00"


def test_format_utc_offset_utc() -> None:
    moment = datetime(2026, 1, 15, 12, 0, tzinfo=ZoneInfo("UTC"))
    assert _format_utc_offset("UTC", now=moment) == "UTC"


def test_format_utc_offset_negative() -> None:
    moment = datetime(2026, 1, 15, 12, 0, tzinfo=ZoneInfo("America/New_York"))
    # January → EST → UTC-5
    assert _format_utc_offset("America/New_York", now=moment) == "UTC-05:00"


def test_countries_with_zones_returns_non_empty_for_each_continent() -> None:
    for continent in (CONTINENT_EUROPE, CONTINENT_ASIA, "america", CONTINENT_OTHER):
        pairs = _countries_with_zones(continent)
        assert pairs, f"Continent {continent} has no live countries"
        for country, zones in pairs:
            assert country
            assert zones


# ── start_timezone_setup ─────────────────────────────────────────────────────


async def test_start_timezone_setup_sets_state_and_sends_keyboard() -> None:
    msg = make_message()
    state = make_state()

    await start_timezone_setup(msg, state, "ru")

    state.set_state.assert_awaited_once_with(TimezoneSetupStates.waiting_for_continent)
    msg.answer.assert_awaited_once()
    text = msg.answer.call_args[0][0]
    assert "часовой пояс" in text.lower()
    kb = msg.answer.call_args.kwargs["reply_markup"]
    assert kb is _continent_keyboard("ru") or kb.inline_keyboard  # keyboard was passed


# ── cb_pick_continent ────────────────────────────────────────────────────────


async def test_cb_pick_continent_advances_to_country() -> None:
    cb = make_callback(f"{_CB_CONTINENT}{CONTINENT_EUROPE}")
    state = make_state()

    await cb_pick_continent(cb, state)

    state.set_state.assert_awaited_with(TimezoneSetupStates.waiting_for_country)
    cb.message.edit_text.assert_awaited_once()
    stored = await state.get_data()
    assert stored[_STATE_CONTINENT_KEY] == CONTINENT_EUROPE


async def test_cb_pick_continent_ignores_unknown_continent() -> None:
    cb = make_callback(f"{_CB_CONTINENT}mars")
    state = make_state()

    await cb_pick_continent(cb, state)

    state.set_state.assert_not_awaited()
    cb.message.edit_text.assert_not_awaited()


async def test_cb_pick_continent_without_message_returns_early() -> None:
    cb = make_callback(f"{_CB_CONTINENT}{CONTINENT_EUROPE}")
    cb.message = None
    state = make_state()

    await cb_pick_continent(cb, state)
    state.set_state.assert_not_awaited()


# ── cb_back_to_continent ─────────────────────────────────────────────────────


async def test_cb_back_to_continent_resets_state() -> None:
    cb = make_callback(_CB_BACK_CONTINENT)
    state = make_state({_STATE_CONTINENT_KEY: CONTINENT_EUROPE})

    await cb_back_to_continent(cb, state)

    state.set_state.assert_awaited_with(TimezoneSetupStates.waiting_for_continent)
    cb.message.edit_text.assert_awaited_once()


# ── cb_pick_country ──────────────────────────────────────────────────────────


async def test_cb_pick_country_with_multiple_zones_advances_to_zone_step() -> None:
    # Russia in Europe continent has many zones → zone step required
    state = make_state({_STATE_CONTINENT_KEY: CONTINENT_EUROPE})
    pairs = _countries_with_zones(CONTINENT_EUROPE)
    russia_idx = next(i for i, (slug, _) in enumerate(pairs) if slug == "russia")
    cb = make_callback(f"{_CB_COUNTRY}{russia_idx}")
    svc = make_tz_service()

    await cb_pick_country(cb, state, user_settings_service=svc)

    state.set_state.assert_awaited_with(TimezoneSetupStates.waiting_for_zone)
    cb.message.edit_text.assert_awaited_once()
    stored = await state.get_data()
    # The slug (internal id) is stored — never the localized label.
    assert stored[_STATE_COUNTRY_KEY] == "russia"
    svc.set_timezone.assert_not_awaited()


async def test_cb_pick_country_uses_localized_country_in_prompt() -> None:
    # When advancing to the zone picker, the prompt should show the
    # country in the user's language, not the slug.
    state = make_state({_STATE_CONTINENT_KEY: CONTINENT_EUROPE})
    pairs = _countries_with_zones(CONTINENT_EUROPE)
    russia_idx = next(i for i, (slug, _) in enumerate(pairs) if slug == "russia")
    svc = make_tz_service()

    cb_ru = make_callback(f"{_CB_COUNTRY}{russia_idx}")
    await cb_pick_country(cb_ru, state, user_settings_service=svc, lang="ru")
    prompt_ru = cb_ru.message.edit_text.call_args[0][0]
    assert "Россия" in prompt_ru
    assert "russia" not in prompt_ru

    state_en = make_state({_STATE_CONTINENT_KEY: CONTINENT_EUROPE})
    cb_en = make_callback(f"{_CB_COUNTRY}{russia_idx}")
    await cb_pick_country(cb_en, state_en, user_settings_service=svc, lang="en")
    prompt_en = cb_en.message.edit_text.call_args[0][0]
    assert "Russia" in prompt_en
    assert "Россия" not in prompt_en


async def test_cb_pick_country_with_single_zone_finalizes_immediately() -> None:
    # Germany has exactly one zone → should skip the zone step and save directly
    state = make_state({_STATE_CONTINENT_KEY: CONTINENT_EUROPE})
    pairs = _countries_with_zones(CONTINENT_EUROPE)
    germany_idx = next(i for i, (slug, _) in enumerate(pairs) if slug == "germany")
    cb = make_callback(f"{_CB_COUNTRY}{germany_idx}")
    svc = make_tz_service()

    await cb_pick_country(cb, state, user_settings_service=svc)

    svc.set_timezone.assert_awaited_once_with(cb.from_user.id, "Europe/Berlin")
    state.clear.assert_awaited_once()
    cb.message.edit_text.assert_awaited_once()
    confirmation = cb.message.edit_text.call_args[0][0]
    assert "Europe/Berlin" in confirmation
    assert "UTC" in confirmation


async def test_cb_pick_country_invalid_index_ignored() -> None:
    state = make_state({_STATE_CONTINENT_KEY: CONTINENT_EUROPE})
    cb = make_callback(f"{_CB_COUNTRY}9999")
    svc = make_tz_service()

    await cb_pick_country(cb, state, user_settings_service=svc)

    svc.set_timezone.assert_not_awaited()
    cb.message.edit_text.assert_not_awaited()


async def test_cb_pick_country_non_numeric_index_ignored() -> None:
    state = make_state({_STATE_CONTINENT_KEY: CONTINENT_EUROPE})
    cb = make_callback(f"{_CB_COUNTRY}abc")
    svc = make_tz_service()

    await cb_pick_country(cb, state, user_settings_service=svc)

    svc.set_timezone.assert_not_awaited()


async def test_cb_pick_country_missing_continent_state_ignored() -> None:
    state = make_state()  # no continent stored
    cb = make_callback(f"{_CB_COUNTRY}0")
    svc = make_tz_service()

    await cb_pick_country(cb, state, user_settings_service=svc)

    svc.set_timezone.assert_not_awaited()


async def test_cb_pick_country_service_none_shows_friendly_error() -> None:
    state = make_state({_STATE_CONTINENT_KEY: CONTINENT_EUROPE})
    pairs = _countries_with_zones(CONTINENT_EUROPE)
    germany_idx = next(i for i, (slug, _) in enumerate(pairs) if slug == "germany")
    cb = make_callback(f"{_CB_COUNTRY}{germany_idx}")

    await cb_pick_country(cb, state, user_settings_service=None)

    cb.message.edit_text.assert_awaited_once()
    state.clear.assert_awaited_once()


# ── cb_back_to_country ───────────────────────────────────────────────────────


async def test_cb_back_to_country_returns_to_country_picker() -> None:
    cb = make_callback(_CB_BACK_COUNTRY)
    state = make_state({_STATE_CONTINENT_KEY: CONTINENT_EUROPE})

    await cb_back_to_country(cb, state)

    state.set_state.assert_awaited_with(TimezoneSetupStates.waiting_for_country)
    cb.message.edit_text.assert_awaited_once()


async def test_cb_back_to_country_falls_back_to_continent_when_state_lost() -> None:
    cb = make_callback(_CB_BACK_COUNTRY)
    state = make_state()  # empty — continent missing

    await cb_back_to_country(cb, state)

    state.set_state.assert_awaited_with(TimezoneSetupStates.waiting_for_continent)


# ── cb_pick_zone ─────────────────────────────────────────────────────────────


async def test_cb_pick_zone_saves_and_confirms() -> None:
    state = make_state({_STATE_CONTINENT_KEY: CONTINENT_EUROPE, _STATE_COUNTRY_KEY: "russia"})
    cb = make_callback(f"{_CB_ZONE}0")  # first zone for Russia
    svc = make_tz_service()

    await cb_pick_zone(cb, state, user_settings_service=svc)

    svc.set_timezone.assert_awaited_once()
    saved_zone = svc.set_timezone.call_args[0][1]
    assert saved_zone.startswith("Europe/") or saved_zone.startswith("Asia/")
    state.clear.assert_awaited_once()
    cb.message.edit_text.assert_awaited_once()
    confirmation = cb.message.edit_text.call_args[0][0]
    assert saved_zone in confirmation
    assert "UTC" in confirmation


async def test_cb_pick_zone_invalid_index_ignored() -> None:
    state = make_state({_STATE_CONTINENT_KEY: CONTINENT_EUROPE, _STATE_COUNTRY_KEY: "russia"})
    cb = make_callback(f"{_CB_ZONE}9999")
    svc = make_tz_service()

    await cb_pick_zone(cb, state, user_settings_service=svc)

    svc.set_timezone.assert_not_awaited()


async def test_cb_pick_zone_missing_country_state_ignored() -> None:
    state = make_state({_STATE_CONTINENT_KEY: CONTINENT_EUROPE})  # no country
    cb = make_callback(f"{_CB_ZONE}0")
    svc = make_tz_service()

    await cb_pick_zone(cb, state, user_settings_service=svc)

    svc.set_timezone.assert_not_awaited()


async def test_cb_pick_zone_unknown_country_ignored() -> None:
    state = make_state({_STATE_CONTINENT_KEY: CONTINENT_EUROPE, _STATE_COUNTRY_KEY: "mordor"})
    cb = make_callback(f"{_CB_ZONE}0")
    svc = make_tz_service()

    await cb_pick_zone(cb, state, user_settings_service=svc)

    svc.set_timezone.assert_not_awaited()


async def test_cb_pick_zone_non_numeric_ignored() -> None:
    state = make_state({_STATE_CONTINENT_KEY: CONTINENT_EUROPE, _STATE_COUNTRY_KEY: "russia"})
    cb = make_callback(f"{_CB_ZONE}xyz")
    svc = make_tz_service()

    await cb_pick_zone(cb, state, user_settings_service=svc)

    svc.set_timezone.assert_not_awaited()


async def test_cb_pick_zone_service_none_shows_error() -> None:
    state = make_state({_STATE_CONTINENT_KEY: CONTINENT_EUROPE, _STATE_COUNTRY_KEY: "russia"})
    cb = make_callback(f"{_CB_ZONE}0")

    await cb_pick_zone(cb, state, user_settings_service=None)

    cb.message.edit_text.assert_awaited_once()
    state.clear.assert_awaited_once()


async def test_cb_pick_zone_invalid_timezone_from_service_recovers() -> None:
    state = make_state({_STATE_CONTINENT_KEY: CONTINENT_EUROPE, _STATE_COUNTRY_KEY: "russia"})
    cb = make_callback(f"{_CB_ZONE}0")
    svc = make_tz_service()
    svc.set_timezone = AsyncMock(side_effect=InvalidTimezoneError("bad"))

    await cb_pick_zone(cb, state, user_settings_service=svc)

    # Recovery: we return to the continent picker and don't clear state
    cb.message.edit_text.assert_awaited_once()
    state.set_state.assert_awaited_with(TimezoneSetupStates.waiting_for_continent)
    state.clear.assert_not_awaited()


# ── _country_label localization ──────────────────────────────────────────────


def test_country_label_returns_russian_for_ru() -> None:
    assert _country_label("russia", "ru") == "Россия"
    assert _country_label("germany", "ru") == "Германия"
    assert _country_label("south_korea", "ru") == "Южная Корея"


def test_country_label_returns_english_for_en() -> None:
    assert _country_label("russia", "en") == "Russia"
    assert _country_label("germany", "en") == "Germany"
    assert _country_label("south_korea", "en") == "South Korea"


def test_country_label_falls_back_to_english_for_unknown_language() -> None:
    # Unknown language → fall back to English so we never show the raw slug.
    assert _country_label("russia", "fr") == "Russia"


def test_country_label_unknown_slug_renders_title_case() -> None:
    # Newly added countries without a translation entry render readably.
    assert _country_label("new_country", "ru") == "New Country"
    assert _country_label("new_country", "en") == "New Country"
    assert _country_label("singleword", "en") == "Singleword"


def test_every_country_slug_has_localizations() -> None:
    # Hard guard: every slug used in the data must have ru and en labels so
    # we never show a fallback in production.
    all_slugs: set[str] = set()
    for countries in _CONTINENT_COUNTRIES.values():
        all_slugs.update(countries.keys())
    missing_ru = [s for s in all_slugs if "ru" not in _COUNTRY_LABELS.get(s, {})]
    missing_en = [s for s in all_slugs if "en" not in _COUNTRY_LABELS.get(s, {})]
    assert not missing_ru, f"slugs missing ru translation: {missing_ru}"
    assert not missing_en, f"slugs missing en translation: {missing_en}"


def test_country_dictionary_keys_are_ascii_slugs() -> None:
    # The slug is what the FSM persists and what callbacks key off of —
    # it must stay ASCII-safe and free of UI-language drift.
    for countries in _CONTINENT_COUNTRIES.values():
        for slug in countries:
            assert slug.isascii(), f"non-ASCII slug: {slug!r}"
            assert slug == slug.lower(), f"slug must be lowercase: {slug!r}"
            assert " " not in slug, f"slug must not contain spaces: {slug!r}"
