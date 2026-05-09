"""FSM dialog for selecting user timezone: continent → country → city.

Triggered on /start when the user has no stored timezone. Re-used by /config timezone
(see issue #65). Keyboards are built from real IANA zones via `zoneinfo.available_timezones()`.
"""

from datetime import datetime
from zoneinfo import ZoneInfo, available_timezones

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.exceptions import InvalidTimezoneError
from bot.i18n import t
from bot.services.user_settings_service import UserSettingsService

router = Router(name="timezone_setup")


# ─────────────────────────────────────────────────────────────────────────────
# Continent → country → IANA zones mapping
#
# IANA zones are in the form `Continent/City` (or `Continent/SubRegion/City`),
# not `Continent/Country/City`. To give users a country-centric flow we keep a
# curated mapping of popular countries to their canonical zones. At runtime we
# intersect with `zoneinfo.available_timezones()` so only zones shipped with the
# current tzdata are offered.
#
# Coverage goal from issue #64: ≥ 95% of users. Russia, CIS, EU, Asian hubs,
# North and South America are covered; less common regions fall under "Other".
#
# Country dict keys are ASCII slugs (e.g. ``"russia"``) — internal identifiers
# that decouple data from UI. Localized country names live in `_COUNTRY_LABELS`
# (issue #122). Adding a country without an entry in `_COUNTRY_LABELS` is safe:
# `_country_label` falls back to the slug rendered in title case so the picker
# stays usable until the translation is added.
# ─────────────────────────────────────────────────────────────────────────────

CONTINENT_EUROPE = "europe"
CONTINENT_ASIA = "asia"
CONTINENT_AMERICA = "america"
CONTINENT_OTHER = "other"

_CONTINENT_LABEL_KEY = {
    CONTINENT_EUROPE: "tz_continent_europe",
    CONTINENT_ASIA: "tz_continent_asia",
    CONTINENT_AMERICA: "tz_continent_america",
    CONTINENT_OTHER: "tz_continent_other",
}


def _continent_label(continent: str, lang: str) -> str:
    """Return the localized label for a continent key."""
    return t(_CONTINENT_LABEL_KEY[continent], lang)


# Each country slug maps to the list of IANA zones that belong to it.
# Order inside each list is preserved when rendering the zone picker.
_EUROPE_COUNTRIES: dict[str, list[str]] = {
    "russia": [
        "Europe/Kaliningrad",
        "Europe/Moscow",
        "Europe/Samara",
        "Europe/Volgograd",
        "Europe/Saratov",
        "Europe/Astrakhan",
        "Europe/Ulyanovsk",
        "Europe/Kirov",
        "Asia/Yekaterinburg",
        "Asia/Omsk",
        "Asia/Novosibirsk",
        "Asia/Novokuznetsk",
        "Asia/Krasnoyarsk",
        "Asia/Irkutsk",
        "Asia/Chita",
        "Asia/Yakutsk",
        "Asia/Khandyga",
        "Asia/Vladivostok",
        "Asia/Ust-Nera",
        "Asia/Magadan",
        "Asia/Sakhalin",
        "Asia/Srednekolymsk",
        "Asia/Kamchatka",
        "Asia/Anadyr",
    ],
    "ukraine": ["Europe/Kyiv", "Europe/Simferopol"],
    "belarus": ["Europe/Minsk"],
    "uk": ["Europe/London"],
    "germany": ["Europe/Berlin"],
    "france": ["Europe/Paris"],
    "spain": ["Europe/Madrid"],
    "italy": ["Europe/Rome"],
    "netherlands": ["Europe/Amsterdam"],
    "poland": ["Europe/Warsaw"],
    "czechia": ["Europe/Prague"],
    "austria": ["Europe/Vienna"],
    "switzerland": ["Europe/Zurich"],
    "sweden": ["Europe/Stockholm"],
    "norway": ["Europe/Oslo"],
    "finland": ["Europe/Helsinki"],
    "denmark": ["Europe/Copenhagen"],
    "portugal": ["Europe/Lisbon"],
    "greece": ["Europe/Athens"],
    "turkey": ["Europe/Istanbul"],
    "romania": ["Europe/Bucharest"],
    "bulgaria": ["Europe/Sofia"],
    "hungary": ["Europe/Budapest"],
    "ireland": ["Europe/Dublin"],
    "serbia": ["Europe/Belgrade"],
    "latvia": ["Europe/Riga"],
    "lithuania": ["Europe/Vilnius"],
    "estonia": ["Europe/Tallinn"],
    "moldova": ["Europe/Chisinau"],
}

_ASIA_COUNTRIES: dict[str, list[str]] = {
    "kazakhstan": ["Asia/Almaty", "Asia/Aqtau", "Asia/Aqtobe", "Asia/Atyrau", "Asia/Oral"],
    "uzbekistan": ["Asia/Tashkent", "Asia/Samarkand"],
    "kyrgyzstan": ["Asia/Bishkek"],
    "tajikistan": ["Asia/Dushanbe"],
    "turkmenistan": ["Asia/Ashgabat"],
    "armenia": ["Asia/Yerevan"],
    "azerbaijan": ["Asia/Baku"],
    "georgia": ["Asia/Tbilisi"],
    "israel": ["Asia/Jerusalem"],
    "uae": ["Asia/Dubai"],
    "saudi_arabia": ["Asia/Riyadh"],
    "india": ["Asia/Kolkata"],
    "pakistan": ["Asia/Karachi"],
    "china": ["Asia/Shanghai"],
    "japan": ["Asia/Tokyo"],
    "south_korea": ["Asia/Seoul"],
    "thailand": ["Asia/Bangkok"],
    "vietnam": ["Asia/Ho_Chi_Minh"],
    "singapore": ["Asia/Singapore"],
    "indonesia": ["Asia/Jakarta", "Asia/Makassar", "Asia/Jayapura"],
    "philippines": ["Asia/Manila"],
    "malaysia": ["Asia/Kuala_Lumpur"],
    "iran": ["Asia/Tehran"],
}

_AMERICA_COUNTRIES: dict[str, list[str]] = {
    "usa": [
        "America/New_York",
        "America/Chicago",
        "America/Denver",
        "America/Phoenix",
        "America/Los_Angeles",
        "America/Anchorage",
        "Pacific/Honolulu",
    ],
    "canada": [
        "America/Toronto",
        "America/Winnipeg",
        "America/Edmonton",
        "America/Vancouver",
        "America/Halifax",
        "America/St_Johns",
    ],
    "mexico": ["America/Mexico_City", "America/Cancun", "America/Tijuana"],
    "brazil": ["America/Sao_Paulo", "America/Manaus", "America/Fortaleza"],
    "argentina": ["America/Argentina/Buenos_Aires"],
    "chile": ["America/Santiago"],
    "colombia": ["America/Bogota"],
    "peru": ["America/Lima"],
    "venezuela": ["America/Caracas"],
    "cuba": ["America/Havana"],
}

_OTHER_COUNTRIES: dict[str, list[str]] = {
    "south_africa": ["Africa/Johannesburg"],
    "egypt": ["Africa/Cairo"],
    "morocco": ["Africa/Casablanca"],
    "nigeria": ["Africa/Lagos"],
    "kenya": ["Africa/Nairobi"],
    "australia": [
        "Australia/Sydney",
        "Australia/Melbourne",
        "Australia/Brisbane",
        "Australia/Adelaide",
        "Australia/Perth",
        "Australia/Hobart",
        "Australia/Darwin",
    ],
    "new_zealand": ["Pacific/Auckland"],
    "utc": ["UTC"],
}

_CONTINENT_COUNTRIES: dict[str, dict[str, list[str]]] = {
    CONTINENT_EUROPE: _EUROPE_COUNTRIES,
    CONTINENT_ASIA: _ASIA_COUNTRIES,
    CONTINENT_AMERICA: _AMERICA_COUNTRIES,
    CONTINENT_OTHER: _OTHER_COUNTRIES,
}


# Localized country names. Keyed by the same ASCII slug used in the country
# dictionaries above; the inner mapping covers every supported language. New
# countries that miss a translation gracefully fall back to a title-cased slug
# in `_country_label` (e.g. ``"new_country" -> "New Country"``), so the picker
# always renders something readable.
_COUNTRY_LABELS: dict[str, dict[str, str]] = {
    # Europe
    "russia": {"ru": "Россия", "en": "Russia"},
    "ukraine": {"ru": "Украина", "en": "Ukraine"},
    "belarus": {"ru": "Беларусь", "en": "Belarus"},
    "uk": {"ru": "Великобритания", "en": "United Kingdom"},
    "germany": {"ru": "Германия", "en": "Germany"},
    "france": {"ru": "Франция", "en": "France"},
    "spain": {"ru": "Испания", "en": "Spain"},
    "italy": {"ru": "Италия", "en": "Italy"},
    "netherlands": {"ru": "Нидерланды", "en": "Netherlands"},
    "poland": {"ru": "Польша", "en": "Poland"},
    "czechia": {"ru": "Чехия", "en": "Czechia"},
    "austria": {"ru": "Австрия", "en": "Austria"},
    "switzerland": {"ru": "Швейцария", "en": "Switzerland"},
    "sweden": {"ru": "Швеция", "en": "Sweden"},
    "norway": {"ru": "Норвегия", "en": "Norway"},
    "finland": {"ru": "Финляндия", "en": "Finland"},
    "denmark": {"ru": "Дания", "en": "Denmark"},
    "portugal": {"ru": "Португалия", "en": "Portugal"},
    "greece": {"ru": "Греция", "en": "Greece"},
    "turkey": {"ru": "Турция", "en": "Turkey"},
    "romania": {"ru": "Румыния", "en": "Romania"},
    "bulgaria": {"ru": "Болгария", "en": "Bulgaria"},
    "hungary": {"ru": "Венгрия", "en": "Hungary"},
    "ireland": {"ru": "Ирландия", "en": "Ireland"},
    "serbia": {"ru": "Сербия", "en": "Serbia"},
    "latvia": {"ru": "Латвия", "en": "Latvia"},
    "lithuania": {"ru": "Литва", "en": "Lithuania"},
    "estonia": {"ru": "Эстония", "en": "Estonia"},
    "moldova": {"ru": "Молдова", "en": "Moldova"},
    # Asia
    "kazakhstan": {"ru": "Казахстан", "en": "Kazakhstan"},
    "uzbekistan": {"ru": "Узбекистан", "en": "Uzbekistan"},
    "kyrgyzstan": {"ru": "Кыргызстан", "en": "Kyrgyzstan"},
    "tajikistan": {"ru": "Таджикистан", "en": "Tajikistan"},
    "turkmenistan": {"ru": "Туркменистан", "en": "Turkmenistan"},
    "armenia": {"ru": "Армения", "en": "Armenia"},
    "azerbaijan": {"ru": "Азербайджан", "en": "Azerbaijan"},
    "georgia": {"ru": "Грузия", "en": "Georgia"},
    "israel": {"ru": "Израиль", "en": "Israel"},
    "uae": {"ru": "ОАЭ", "en": "UAE"},
    "saudi_arabia": {"ru": "Саудовская Аравия", "en": "Saudi Arabia"},
    "india": {"ru": "Индия", "en": "India"},
    "pakistan": {"ru": "Пакистан", "en": "Pakistan"},
    "china": {"ru": "Китай", "en": "China"},
    "japan": {"ru": "Япония", "en": "Japan"},
    "south_korea": {"ru": "Южная Корея", "en": "South Korea"},
    "thailand": {"ru": "Таиланд", "en": "Thailand"},
    "vietnam": {"ru": "Вьетнам", "en": "Vietnam"},
    "singapore": {"ru": "Сингапур", "en": "Singapore"},
    "indonesia": {"ru": "Индонезия", "en": "Indonesia"},
    "philippines": {"ru": "Филиппины", "en": "Philippines"},
    "malaysia": {"ru": "Малайзия", "en": "Malaysia"},
    "iran": {"ru": "Иран", "en": "Iran"},
    # America
    "usa": {"ru": "США", "en": "USA"},
    "canada": {"ru": "Канада", "en": "Canada"},
    "mexico": {"ru": "Мексика", "en": "Mexico"},
    "brazil": {"ru": "Бразилия", "en": "Brazil"},
    "argentina": {"ru": "Аргентина", "en": "Argentina"},
    "chile": {"ru": "Чили", "en": "Chile"},
    "colombia": {"ru": "Колумбия", "en": "Colombia"},
    "peru": {"ru": "Перу", "en": "Peru"},
    "venezuela": {"ru": "Венесуэла", "en": "Venezuela"},
    "cuba": {"ru": "Куба", "en": "Cuba"},
    # Other
    "south_africa": {"ru": "ЮАР", "en": "South Africa"},
    "egypt": {"ru": "Египет", "en": "Egypt"},
    "morocco": {"ru": "Марокко", "en": "Morocco"},
    "nigeria": {"ru": "Нигерия", "en": "Nigeria"},
    "kenya": {"ru": "Кения", "en": "Kenya"},
    "australia": {"ru": "Австралия", "en": "Australia"},
    "new_zealand": {"ru": "Новая Зеландия", "en": "New Zealand"},
    "utc": {"ru": "UTC", "en": "UTC"},
}


def _country_label(slug: str, lang: str) -> str:
    """Return the localized country name for a slug, falling back gracefully.

    Resolution order:
        1. ``_COUNTRY_LABELS[slug][lang]`` — exact match for the requested language.
        2. ``_COUNTRY_LABELS[slug]["en"]`` — English fallback.
        3. The slug rendered in title case (``"new_country"`` → ``"New Country"``)
           so newly added countries without translations still appear sensibly.
    """
    translations = _COUNTRY_LABELS.get(slug)
    if translations is not None:
        label = translations.get(lang) or translations.get("en")
        if label:
            return label
    return slug.replace("_", " ").title()


class TimezoneSetupStates(StatesGroup):
    """FSM states for the three-step timezone picker."""

    waiting_for_continent = State()
    waiting_for_country = State()
    waiting_for_zone = State()


# Callback data prefixes — kept short to stay within Telegram's 64-byte limit.
_CB_CONTINENT = "tzc:"  # continent
_CB_COUNTRY = "tzn:"  # country index
_CB_ZONE = "tzz:"  # zone index
_CB_BACK_CONTINENT = "tzb:c"
_CB_BACK_COUNTRY = "tzb:n"

_STATE_CONTINENT_KEY = "tz_continent"
_STATE_COUNTRY_KEY = "tz_country"

_ROW_WIDTH = 2


def _available_zones_for(country_zones: list[str]) -> list[str]:
    """Return the subset of country_zones that actually exists in the current tzdata."""
    present = available_timezones()
    return [z for z in country_zones if z in present]


def _countries_with_zones(continent: str) -> list[tuple[str, list[str]]]:
    """Return (slug, zones) pairs for a continent, dropping entries with no live zones."""
    result: list[tuple[str, list[str]]] = []
    for slug, zones in _CONTINENT_COUNTRIES[continent].items():
        live = _available_zones_for(zones)
        if live:
            result.append((slug, live))
    return result


def _chunk(items: list, width: int) -> list[list]:
    """Split a flat list into rows of at most `width` items."""
    return [items[i : i + width] for i in range(0, len(items), width)]


def _continent_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Build the step-1 keyboard with the four continent choices."""
    buttons = [
        InlineKeyboardButton(text=_continent_label(c, lang), callback_data=f"{_CB_CONTINENT}{c}")
        for c in (CONTINENT_EUROPE, CONTINENT_ASIA, CONTINENT_AMERICA, CONTINENT_OTHER)
    ]
    return InlineKeyboardMarkup(inline_keyboard=_chunk(buttons, _ROW_WIDTH))


def _country_keyboard(
    continent: str, lang: str
) -> tuple[InlineKeyboardMarkup, list[tuple[str, list[str]]]]:
    """Build the step-2 keyboard; return (keyboard, ordered [slug, zones] pairs)."""
    pairs = _countries_with_zones(continent)
    buttons = [
        InlineKeyboardButton(text=_country_label(slug, lang), callback_data=f"{_CB_COUNTRY}{idx}")
        for idx, (slug, _) in enumerate(pairs)
    ]
    rows = _chunk(buttons, _ROW_WIDTH)
    rows.append(
        [InlineKeyboardButton(text=t("pagination_prev", lang), callback_data=_CB_BACK_CONTINENT)]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows), pairs


def _zone_keyboard(zones: list[str], lang: str) -> InlineKeyboardMarkup:
    """Build the step-3 keyboard listing each IANA zone for the country."""
    buttons = [
        InlineKeyboardButton(text=_zone_label(z), callback_data=f"{_CB_ZONE}{idx}")
        for idx, z in enumerate(zones)
    ]
    rows = _chunk(buttons, _ROW_WIDTH)
    rows.append(
        [InlineKeyboardButton(text=t("pagination_prev", lang), callback_data=_CB_BACK_COUNTRY)]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _zone_label(zone: str) -> str:
    """Return a human-friendly label for an IANA zone (city part only)."""
    if "/" not in zone:
        return zone
    return zone.rsplit("/", 1)[1].replace("_", " ")


def _format_utc_offset(zone: str, now: datetime | None = None) -> str:
    """Return the zone's current UTC offset formatted as `UTC+03:00` (or `UTC` for zero)."""
    moment = now or datetime.now(tz=ZoneInfo(zone))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo(zone))
    else:
        moment = moment.astimezone(ZoneInfo(zone))
    offset = moment.utcoffset()
    if offset is None:
        return "UTC"
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)
    hours, minutes = divmod(total_minutes, 60)
    if hours == 0 and minutes == 0:
        return "UTC"
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


async def start_timezone_setup(message: Message, state: FSMContext, lang: str = "en") -> None:
    """Entry point: show the continent picker and enter the FSM.

    Reusable by /start (on first run) and by /config timezone (issue #65).
    """
    await state.set_state(TimezoneSetupStates.waiting_for_continent)
    await message.answer(
        t("tz_choose_continent", lang),
        reply_markup=_continent_keyboard(lang),
    )


@router.callback_query(TimezoneSetupStates.waiting_for_continent, F.data.startswith(_CB_CONTINENT))
async def cb_pick_continent(callback: CallbackQuery, state: FSMContext, lang: str = "en") -> None:
    """Handle continent selection — advance to the country picker."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    continent = callback.data.removeprefix(_CB_CONTINENT)
    if continent not in _CONTINENT_COUNTRIES:
        return

    keyboard, pairs = _country_keyboard(continent, lang)
    if not pairs:
        # Should never happen with the curated mapping, but fail gracefully.
        await callback.message.edit_text(
            t("tz_no_zones_on_continent", lang),
            reply_markup=_continent_keyboard(lang),
        )
        return

    await state.update_data({_STATE_CONTINENT_KEY: continent})
    await state.set_state(TimezoneSetupStates.waiting_for_country)
    await callback.message.edit_text(
        t("tz_choose_country", lang, continent=_continent_label(continent, lang)),
        reply_markup=keyboard,
    )


@router.callback_query(TimezoneSetupStates.waiting_for_country, F.data == _CB_BACK_CONTINENT)
async def cb_back_to_continent(
    callback: CallbackQuery, state: FSMContext, lang: str = "en"
) -> None:
    """Step back from the country picker to the continent picker."""
    await callback.answer()
    if callback.message is None:
        return
    await state.set_state(TimezoneSetupStates.waiting_for_continent)
    await callback.message.edit_text(
        t("tz_choose_continent", lang),
        reply_markup=_continent_keyboard(lang),
    )


@router.callback_query(TimezoneSetupStates.waiting_for_country, F.data.startswith(_CB_COUNTRY))
async def cb_pick_country(
    callback: CallbackQuery,
    state: FSMContext,
    user_settings_service: UserSettingsService | None = None,
    lang: str = "en",
) -> None:
    """Handle country selection — advance to the zone picker, or finish if only one zone."""
    await callback.answer()
    if callback.message is None or callback.data is None or callback.from_user is None:
        return

    data = await state.get_data()
    continent = data.get(_STATE_CONTINENT_KEY)
    if continent not in _CONTINENT_COUNTRIES:
        return

    try:
        idx = int(callback.data.removeprefix(_CB_COUNTRY))
    except ValueError:
        return

    pairs = _countries_with_zones(continent)
    if idx < 0 or idx >= len(pairs):
        return

    country_slug, zones = pairs[idx]

    if len(zones) == 1:
        await _finalize_zone(callback, state, zones[0], user_settings_service, lang)
        return

    await state.update_data({_STATE_COUNTRY_KEY: country_slug})
    await state.set_state(TimezoneSetupStates.waiting_for_zone)
    await callback.message.edit_text(
        t("tz_choose_city", lang, country=_country_label(country_slug, lang)),
        reply_markup=_zone_keyboard(zones, lang),
    )


@router.callback_query(TimezoneSetupStates.waiting_for_zone, F.data == _CB_BACK_COUNTRY)
async def cb_back_to_country(callback: CallbackQuery, state: FSMContext, lang: str = "en") -> None:
    """Step back from the zone picker to the country picker."""
    await callback.answer()
    if callback.message is None:
        return
    data = await state.get_data()
    continent = data.get(_STATE_CONTINENT_KEY)
    if continent not in _CONTINENT_COUNTRIES:
        await state.set_state(TimezoneSetupStates.waiting_for_continent)
        await callback.message.edit_text(
            t("tz_choose_continent", lang),
            reply_markup=_continent_keyboard(lang),
        )
        return
    keyboard, _ = _country_keyboard(continent, lang)
    await state.set_state(TimezoneSetupStates.waiting_for_country)
    await callback.message.edit_text(
        t("tz_choose_country", lang, continent=_continent_label(continent, lang)),
        reply_markup=keyboard,
    )


@router.callback_query(TimezoneSetupStates.waiting_for_zone, F.data.startswith(_CB_ZONE))
async def cb_pick_zone(
    callback: CallbackQuery,
    state: FSMContext,
    user_settings_service: UserSettingsService | None = None,
    lang: str = "en",
) -> None:
    """Handle zone selection — persist the timezone and send the confirmation."""
    await callback.answer()
    if callback.message is None or callback.data is None or callback.from_user is None:
        return

    data = await state.get_data()
    continent = data.get(_STATE_CONTINENT_KEY)
    country_slug = data.get(_STATE_COUNTRY_KEY)
    if continent not in _CONTINENT_COUNTRIES or not country_slug:
        return

    try:
        idx = int(callback.data.removeprefix(_CB_ZONE))
    except ValueError:
        return

    zones = dict(_countries_with_zones(continent)).get(country_slug, [])
    if idx < 0 or idx >= len(zones):
        return

    await _finalize_zone(callback, state, zones[idx], user_settings_service, lang)


async def _finalize_zone(
    callback: CallbackQuery,
    state: FSMContext,
    zone: str,
    user_settings_service: UserSettingsService | None,
    lang: str,
) -> None:
    """Save the selected IANA zone and reply with confirmation; clears FSM state."""
    if callback.message is None or callback.from_user is None:
        return
    if user_settings_service is None:
        await callback.message.edit_text(
            t("tz_settings_service_unavailable", lang),
            reply_markup=None,
        )
        await state.clear()
        return

    try:
        await user_settings_service.set_timezone(callback.from_user.id, zone)
    except InvalidTimezoneError:
        await callback.message.edit_text(
            t("tz_save_failed", lang),
            reply_markup=_continent_keyboard(lang),
        )
        await state.set_state(TimezoneSetupStates.waiting_for_continent)
        return

    await state.clear()
    offset = _format_utc_offset(zone)
    await callback.message.edit_text(
        t("tz_saved", lang, zone=zone, offset=offset),
        reply_markup=None,
    )
