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
# ─────────────────────────────────────────────────────────────────────────────

CONTINENT_EUROPE = "europe"
CONTINENT_ASIA = "asia"
CONTINENT_AMERICA = "america"
CONTINENT_OTHER = "other"

_CONTINENT_LABEL = {
    CONTINENT_EUROPE: "Европа",
    CONTINENT_ASIA: "Азия",
    CONTINENT_AMERICA: "Америка",
    CONTINENT_OTHER: "Другое",
}

# Each country maps to the list of IANA zones that belong to it.
# Order inside each list is preserved when rendering the zone picker.
_EUROPE_COUNTRIES: dict[str, list[str]] = {
    "Россия": [
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
    "Украина": ["Europe/Kyiv", "Europe/Simferopol"],
    "Беларусь": ["Europe/Minsk"],
    "Великобритания": ["Europe/London"],
    "Германия": ["Europe/Berlin"],
    "Франция": ["Europe/Paris"],
    "Испания": ["Europe/Madrid"],
    "Италия": ["Europe/Rome"],
    "Нидерланды": ["Europe/Amsterdam"],
    "Польша": ["Europe/Warsaw"],
    "Чехия": ["Europe/Prague"],
    "Австрия": ["Europe/Vienna"],
    "Швейцария": ["Europe/Zurich"],
    "Швеция": ["Europe/Stockholm"],
    "Норвегия": ["Europe/Oslo"],
    "Финляндия": ["Europe/Helsinki"],
    "Дания": ["Europe/Copenhagen"],
    "Португалия": ["Europe/Lisbon"],
    "Греция": ["Europe/Athens"],
    "Турция": ["Europe/Istanbul"],
    "Румыния": ["Europe/Bucharest"],
    "Болгария": ["Europe/Sofia"],
    "Венгрия": ["Europe/Budapest"],
    "Ирландия": ["Europe/Dublin"],
    "Сербия": ["Europe/Belgrade"],
    "Латвия": ["Europe/Riga"],
    "Литва": ["Europe/Vilnius"],
    "Эстония": ["Europe/Tallinn"],
    "Молдова": ["Europe/Chisinau"],
}

_ASIA_COUNTRIES: dict[str, list[str]] = {
    "Казахстан": ["Asia/Almaty", "Asia/Aqtau", "Asia/Aqtobe", "Asia/Atyrau", "Asia/Oral"],
    "Узбекистан": ["Asia/Tashkent", "Asia/Samarkand"],
    "Кыргызстан": ["Asia/Bishkek"],
    "Таджикистан": ["Asia/Dushanbe"],
    "Туркменистан": ["Asia/Ashgabat"],
    "Армения": ["Asia/Yerevan"],
    "Азербайджан": ["Asia/Baku"],
    "Грузия": ["Asia/Tbilisi"],
    "Израиль": ["Asia/Jerusalem"],
    "ОАЭ": ["Asia/Dubai"],
    "Саудовская Аравия": ["Asia/Riyadh"],
    "Индия": ["Asia/Kolkata"],
    "Пакистан": ["Asia/Karachi"],
    "Китай": ["Asia/Shanghai"],
    "Япония": ["Asia/Tokyo"],
    "Южная Корея": ["Asia/Seoul"],
    "Таиланд": ["Asia/Bangkok"],
    "Вьетнам": ["Asia/Ho_Chi_Minh"],
    "Сингапур": ["Asia/Singapore"],
    "Индонезия": ["Asia/Jakarta", "Asia/Makassar", "Asia/Jayapura"],
    "Филиппины": ["Asia/Manila"],
    "Малайзия": ["Asia/Kuala_Lumpur"],
    "Иран": ["Asia/Tehran"],
}

_AMERICA_COUNTRIES: dict[str, list[str]] = {
    "США": [
        "America/New_York",
        "America/Chicago",
        "America/Denver",
        "America/Phoenix",
        "America/Los_Angeles",
        "America/Anchorage",
        "Pacific/Honolulu",
    ],
    "Канада": [
        "America/Toronto",
        "America/Winnipeg",
        "America/Edmonton",
        "America/Vancouver",
        "America/Halifax",
        "America/St_Johns",
    ],
    "Мексика": ["America/Mexico_City", "America/Cancun", "America/Tijuana"],
    "Бразилия": ["America/Sao_Paulo", "America/Manaus", "America/Fortaleza"],
    "Аргентина": ["America/Argentina/Buenos_Aires"],
    "Чили": ["America/Santiago"],
    "Колумбия": ["America/Bogota"],
    "Перу": ["America/Lima"],
    "Венесуэла": ["America/Caracas"],
    "Куба": ["America/Havana"],
}

_OTHER_COUNTRIES: dict[str, list[str]] = {
    "ЮАР": ["Africa/Johannesburg"],
    "Египет": ["Africa/Cairo"],
    "Марокко": ["Africa/Casablanca"],
    "Нигерия": ["Africa/Lagos"],
    "Кения": ["Africa/Nairobi"],
    "Австралия": [
        "Australia/Sydney",
        "Australia/Melbourne",
        "Australia/Brisbane",
        "Australia/Adelaide",
        "Australia/Perth",
        "Australia/Hobart",
        "Australia/Darwin",
    ],
    "Новая Зеландия": ["Pacific/Auckland"],
    "UTC": ["UTC"],
}

_CONTINENT_COUNTRIES: dict[str, dict[str, list[str]]] = {
    CONTINENT_EUROPE: _EUROPE_COUNTRIES,
    CONTINENT_ASIA: _ASIA_COUNTRIES,
    CONTINENT_AMERICA: _AMERICA_COUNTRIES,
    CONTINENT_OTHER: _OTHER_COUNTRIES,
}


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
    """Return (country, zones) pairs for a continent, dropping entries with no live zones."""
    result: list[tuple[str, list[str]]] = []
    for country, zones in _CONTINENT_COUNTRIES[continent].items():
        live = _available_zones_for(zones)
        if live:
            result.append((country, live))
    return result


def _chunk(items: list, width: int) -> list[list]:
    """Split a flat list into rows of at most `width` items."""
    return [items[i : i + width] for i in range(0, len(items), width)]


def _continent_keyboard() -> InlineKeyboardMarkup:
    """Build the step-1 keyboard with the four continent choices."""
    buttons = [
        InlineKeyboardButton(text=_CONTINENT_LABEL[c], callback_data=f"{_CB_CONTINENT}{c}")
        for c in (CONTINENT_EUROPE, CONTINENT_ASIA, CONTINENT_AMERICA, CONTINENT_OTHER)
    ]
    return InlineKeyboardMarkup(inline_keyboard=_chunk(buttons, _ROW_WIDTH))


def _country_keyboard(continent: str) -> tuple[InlineKeyboardMarkup, list[tuple[str, list[str]]]]:
    """Build the step-2 keyboard; return (keyboard, ordered [country, zones] pairs)."""
    pairs = _countries_with_zones(continent)
    buttons = [
        InlineKeyboardButton(text=country, callback_data=f"{_CB_COUNTRY}{idx}")
        for idx, (country, _) in enumerate(pairs)
    ]
    rows = _chunk(buttons, _ROW_WIDTH)
    rows.append([InlineKeyboardButton(text="← Назад", callback_data=_CB_BACK_CONTINENT)])
    return InlineKeyboardMarkup(inline_keyboard=rows), pairs


def _zone_keyboard(zones: list[str]) -> InlineKeyboardMarkup:
    """Build the step-3 keyboard listing each IANA zone for the country."""
    buttons = [
        InlineKeyboardButton(text=_zone_label(z), callback_data=f"{_CB_ZONE}{idx}")
        for idx, z in enumerate(zones)
    ]
    rows = _chunk(buttons, _ROW_WIDTH)
    rows.append([InlineKeyboardButton(text="← Назад", callback_data=_CB_BACK_COUNTRY)])
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


async def start_timezone_setup(message: Message, state: FSMContext) -> None:
    """Entry point: show the continent picker and enter the FSM.

    Reusable by /start (on first run) and by /config timezone (issue #65).
    """
    await state.set_state(TimezoneSetupStates.waiting_for_continent)
    await message.answer(
        "Давай настроим твой часовой пояс. Выбери континент:",
        reply_markup=_continent_keyboard(),
    )


@router.callback_query(TimezoneSetupStates.waiting_for_continent, F.data.startswith(_CB_CONTINENT))
async def cb_pick_continent(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle continent selection — advance to the country picker."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    continent = callback.data.removeprefix(_CB_CONTINENT)
    if continent not in _CONTINENT_COUNTRIES:
        return

    keyboard, pairs = _country_keyboard(continent)
    if not pairs:
        # Should never happen with the curated mapping, but fail gracefully.
        await callback.message.edit_text(
            "Для этого континента нет доступных зон. Попробуй другой.",
            reply_markup=_continent_keyboard(),
        )
        return

    await state.update_data({_STATE_CONTINENT_KEY: continent})
    await state.set_state(TimezoneSetupStates.waiting_for_country)
    await callback.message.edit_text(
        f"Континент: <b>{_CONTINENT_LABEL[continent]}</b>\nТеперь выбери страну:",
        reply_markup=keyboard,
    )


@router.callback_query(TimezoneSetupStates.waiting_for_country, F.data == _CB_BACK_CONTINENT)
async def cb_back_to_continent(callback: CallbackQuery, state: FSMContext) -> None:
    """Step back from the country picker to the continent picker."""
    await callback.answer()
    if callback.message is None:
        return
    await state.set_state(TimezoneSetupStates.waiting_for_continent)
    await callback.message.edit_text(
        "Давай настроим твой часовой пояс. Выбери континент:",
        reply_markup=_continent_keyboard(),
    )


@router.callback_query(TimezoneSetupStates.waiting_for_country, F.data.startswith(_CB_COUNTRY))
async def cb_pick_country(
    callback: CallbackQuery,
    state: FSMContext,
    user_settings_service: UserSettingsService | None = None,
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

    country, zones = pairs[idx]

    if len(zones) == 1:
        await _finalize_zone(callback, state, zones[0], user_settings_service)
        return

    await state.update_data({_STATE_COUNTRY_KEY: country})
    await state.set_state(TimezoneSetupStates.waiting_for_zone)
    await callback.message.edit_text(
        f"Страна: <b>{country}</b>\nВыбери город / часовой пояс:",
        reply_markup=_zone_keyboard(zones),
    )


@router.callback_query(TimezoneSetupStates.waiting_for_zone, F.data == _CB_BACK_COUNTRY)
async def cb_back_to_country(callback: CallbackQuery, state: FSMContext) -> None:
    """Step back from the zone picker to the country picker."""
    await callback.answer()
    if callback.message is None:
        return
    data = await state.get_data()
    continent = data.get(_STATE_CONTINENT_KEY)
    if continent not in _CONTINENT_COUNTRIES:
        await state.set_state(TimezoneSetupStates.waiting_for_continent)
        await callback.message.edit_text(
            "Давай настроим твой часовой пояс. Выбери континент:",
            reply_markup=_continent_keyboard(),
        )
        return
    keyboard, _ = _country_keyboard(continent)
    await state.set_state(TimezoneSetupStates.waiting_for_country)
    await callback.message.edit_text(
        f"Континент: <b>{_CONTINENT_LABEL[continent]}</b>\nТеперь выбери страну:",
        reply_markup=keyboard,
    )


@router.callback_query(TimezoneSetupStates.waiting_for_zone, F.data.startswith(_CB_ZONE))
async def cb_pick_zone(
    callback: CallbackQuery,
    state: FSMContext,
    user_settings_service: UserSettingsService | None = None,
) -> None:
    """Handle zone selection — persist the timezone and send the confirmation."""
    await callback.answer()
    if callback.message is None or callback.data is None or callback.from_user is None:
        return

    data = await state.get_data()
    continent = data.get(_STATE_CONTINENT_KEY)
    country = data.get(_STATE_COUNTRY_KEY)
    if continent not in _CONTINENT_COUNTRIES or not country:
        return

    try:
        idx = int(callback.data.removeprefix(_CB_ZONE))
    except ValueError:
        return

    zones = dict(_countries_with_zones(continent)).get(country, [])
    if idx < 0 or idx >= len(zones):
        return

    await _finalize_zone(callback, state, zones[idx], user_settings_service)


async def _finalize_zone(
    callback: CallbackQuery,
    state: FSMContext,
    zone: str,
    user_settings_service: UserSettingsService | None,
) -> None:
    """Save the selected IANA zone and reply with confirmation; clears FSM state."""
    if callback.message is None or callback.from_user is None:
        return
    if user_settings_service is None:
        await callback.message.edit_text(
            "Сервис настроек временно недоступен. Попробуй позже.",
            reply_markup=None,
        )
        await state.clear()
        return

    try:
        await user_settings_service.set_timezone(callback.from_user.id, zone)
    except InvalidTimezoneError:
        await callback.message.edit_text(
            "Не удалось сохранить выбранный часовой пояс. Попробуй ещё раз.",
            reply_markup=_continent_keyboard(),
        )
        await state.set_state(TimezoneSetupStates.waiting_for_continent)
        return

    await state.clear()
    offset = _format_utc_offset(zone)
    await callback.message.edit_text(
        f"✅ Часовой пояс установлен: <b>{zone}</b> ({offset})",
        reply_markup=None,
    )
