"""Unit tests for bot.i18n — translation lookup, fallback, and formatting."""

import pytest

from bot.i18n import _EN, _RU, DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, language_name, t


def test_supported_languages_are_exactly_ru_and_en() -> None:
    """Both languages are advertised as supported."""
    assert frozenset({"ru", "en"}) == SUPPORTED_LANGUAGES


def test_default_language_is_en() -> None:
    """English is the canonical fallback language."""
    assert DEFAULT_LANGUAGE == "en"


def test_english_table_is_complete_superset_of_russian() -> None:
    """Every key present in Russian must also exist in English (the fallback source)."""
    missing = set(_RU) - set(_EN)
    assert missing == set(), f"English table is missing keys: {missing}"


def test_russian_and_english_tables_have_the_same_keys() -> None:
    """Both languages must be fully populated — no language-specific-only keys."""
    ru_only = set(_RU) - set(_EN)
    en_only = set(_EN) - set(_RU)
    assert ru_only == set(), f"ru has keys missing in en: {ru_only}"
    assert en_only == set(), f"en has keys missing in ru: {en_only}"


def test_returns_russian_string_when_lang_ru() -> None:
    """A known key returns the Russian translation for lang='ru'."""
    assert t("task_saved", "ru") == "✅ Задача сохранена!"


def test_returns_english_string_when_lang_en() -> None:
    """A known key returns the English translation for lang='en'."""
    assert t("task_saved", "en") == "✅ Task saved!"


def test_kwargs_formatting_works_for_ru() -> None:
    """Named placeholders are substituted via str.format."""
    result = t("reminder_created", "ru", formatted="завтра в 10:00")
    assert result == "🔔 Напомню завтра в 10:00!"


def test_kwargs_formatting_works_for_en() -> None:
    """Named placeholders are substituted in English too."""
    result = t("reminder_created", "en", formatted="tomorrow at 10:00")
    assert result == "🔔 I'll remind you tomorrow at 10:00!"


def test_kwargs_with_multiple_placeholders() -> None:
    """Multiple placeholders on a single template all resolve."""
    result = t("reminder_time_parse_retry", "ru", attempts=2, max_attempts=3)
    assert "2/3" in result
    assert "завтра" in result  # example text kept in the RU template


def test_fallback_to_english_when_key_missing_in_ru(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the Russian table lacks a key, English is used."""
    monkeypatch.setitem(_EN, "__test_only_key__", "English fallback value")
    # _RU deliberately does NOT contain "__test_only_key__" — no monkeypatch there.
    assert t("__test_only_key__", "ru") == "English fallback value"


def test_fallback_for_unknown_language_uses_english() -> None:
    """An unknown language falls back to English rather than erroring."""
    assert t("task_saved", "de") == "✅ Task saved!"


def test_missing_key_returns_raw_key_as_last_resort() -> None:
    """If a key is missing in both languages the raw key is returned (not KeyError)."""
    result = t("this_key_does_not_exist_anywhere", "ru")
    assert result == "this_key_does_not_exist_anywhere"


def test_missing_key_with_kwargs_still_returns_raw_key() -> None:
    """Passing kwargs on a missing key does not raise — the raw key is returned."""
    result = t("another_missing_key", "en", foo="bar")
    # The raw key doesn't contain {foo} so str.format is a no-op and returns the key.
    assert result == "another_missing_key"


def test_template_with_missing_placeholder_returns_unformatted_string() -> None:
    """A template whose placeholders the caller forgot to supply returns the raw template."""
    # "reminder_created" expects {formatted}, but we don't pass it here.
    result = t("reminder_created", "en", wrong_kwarg="x")
    # It should not crash — fall back to the raw template string.
    assert result == _EN["reminder_created"]


def test_no_kwargs_returns_template_unchanged() -> None:
    """When there are no kwargs, the template is returned verbatim (no .format call)."""
    # "welcome" contains braces-free text; ensure it passes through as-is.
    assert t("welcome", "en") == _EN["welcome"]
    assert t("welcome", "ru") == _RU["welcome"]


def test_button_translations_differ_across_languages() -> None:
    """Buttons are genuinely localized, not just copies of English."""
    assert t("link_btn_summary", "ru") != t("link_btn_summary", "en")
    assert t("reminder_btn_ack", "ru") != t("reminder_btn_ack", "en")
    assert t("pagination_prev", "ru") != t("pagination_prev", "en")


@pytest.mark.parametrize(
    "key",
    [
        "welcome",
        "help_title",
        "help_content_types",
        "help_voice",
        "help_media",
        "help_reminders",
        "help_commands",
        "cancel_nothing_to_cancel",
        "cancel_done",
        "classifier_unavailable",
        "link_saved",
        "link_btn_summary",
        "link_btn_save",
        "link_btn_remind",
        "link_btn_close",
        "link_btn_retry",
        "link_summary_loading",
        "link_summary_result",
        "link_scraping_failed",
        "link_summary_failed",
        "link_saved_confirmation",
        "link_service_unavailable",
        "embedding_unavailable_notice",
        "task_saved",
        "task_saved_with_reminder",
        "task_save_failed",
        "task_btn_remind",
        "reminder_prompt_when",
        "reminder_time_parse_failed_final",
        "reminder_time_parse_retry",
        "reminder_save_failed",
        "reminder_created",
        "reminder_service_unavailable",
        "reminder_btn_snooze_1h",
        "reminder_btn_snooze_1d",
        "reminder_btn_ack",
        "reminder_btn_cancel",
        "reminder_snooze_1h_label",
        "reminder_snooze_1d_label",
        "reminder_snoozed",
        "reminder_snooze_failed",
        "reminder_not_found_or_inactive",
        "reminder_ack_failed",
        "reminder_ack_done",
        "reminder_notification",
        "reminder_auto_completed",
        "reminder_btn_reactivate",
        "reminder_reactivated_marker",
        "reminder_reactivate_failed",
        "reminder_cancelled_marker",
        "reminder_cancel_not_found",
        "reminder_cancel_invalid",
        "idea_saved",
        "idea_save_failed",
        "ideas_command_unavailable",
        "ideas_empty",
        "ideas_header",
        "ideas_total",
        "idea_complexity_simple",
        "idea_complexity_medium",
        "idea_complexity_complex",
        "idea_effort_quick",
        "idea_effort_halfday",
        "idea_effort_day",
        "idea_effort_longterm",
        "idea_suggest_empty",
        "idea_suggest_failed",
        "note_saved",
        "note_save_failed",
        "photo_received_disabled",
        "document_received_disabled",
        "photo_process_failed",
        "document_process_failed",
        "media_open_in_drive",
        "media_category_receipt",
        "media_category_document",
        "media_category_screenshot",
        "media_category_photo",
        "media_category_meme",
        "media_category_other",
        "vision_unsupported_format",
        "vision_analyze_failed",
        "vision_media_default",
        "voice_not_configured",
        "voice_transcribed",
        "voice_fallback_saved",
        "transcription_bad_key",
        "transcription_unavailable",
        "transcription_failed",
        "list_command_unavailable",
        "list_empty",
        "list_header_all",
        "list_header_filtered",
        "list_total",
        "list_filter_all",
        "list_filter_links",
        "list_filter_tasks",
        "list_filter_ideas",
        "list_filter_notes",
        "pagination_prev",
        "pagination_next",
        "reminders_command_unavailable",
        "reminders_empty",
        "reminders_entry",
        "search_choose_mode",
        "search_btn_plain",
        "search_btn_smart",
        "search_prompt_plain",
        "search_prompt_smart",
        "search_empty_query",
        "search_service_unavailable",
        "search_semantic_unavailable",
        "search_no_results",
        "search_header_plain",
        "search_header_smart",
        "search_entry_relevance",
        "search_entry_preview",
        "search_label_link",
        "search_label_note",
        "search_label_task",
        "search_label_media",
        "search_label_idea",
        "search_label_record",
        "config_menu_title",
        "config_unknown_setting",
        "config_btn_timezone",
        "tz_choose_continent",
        "tz_no_zones_on_continent",
        "tz_choose_country",
        "tz_choose_city",
        "tz_settings_service_unavailable",
        "tz_save_failed",
        "tz_saved",
        "tz_continent_europe",
        "tz_continent_asia",
        "tz_continent_america",
        "tz_continent_other",
        "botcmd_start",
        "botcmd_list",
        "botcmd_search",
        "botcmd_reminders",
        "botcmd_ideas",
        "botcmd_config",
        "botcmd_cancel",
    ],
)
def test_every_key_is_non_empty_in_both_languages(key: str) -> None:
    """Every declared key has non-empty translations for both ru and en."""
    assert _RU[key], f"Russian value for {key!r} is empty"
    assert _EN[key], f"English value for {key!r} is empty"


def test_templates_with_placeholders_format_in_both_languages() -> None:
    """Representative templates with {placeholders} render correctly in ru and en."""
    # reminder_snoozed uses {period} and {formatted}
    ru = t("reminder_snoozed", "ru", period="1 час", formatted="15:00")
    en = t("reminder_snoozed", "en", period="1 hour", formatted="15:00")
    assert "1 час" in ru and "15:00" in ru
    assert "1 hour" in en and "15:00" in en

    # list_header_filtered uses {label} and {page}
    ru = t("list_header_filtered", "ru", label="🔗 Ссылки", page=2)
    en = t("list_header_filtered", "en", label="🔗 Links", page=2)
    assert "🔗 Ссылки" in ru and "2" in ru
    assert "🔗 Links" in en and "2" in en


def test_unsupported_language_with_kwargs_falls_back_and_formats() -> None:
    """Unknown lang falls back to English AND still applies format kwargs."""
    result = t("reminder_created", "fr", formatted="tomorrow")
    assert result == "🔔 I'll remind you tomorrow!"


# ── language_name helper (used by Claude prompts) ────────────────────────────


def test_language_name_returns_russian_for_ru() -> None:
    """``'ru'`` maps to the English word ``'Russian'`` — used in Claude prompts."""
    assert language_name("ru") == "Russian"


def test_language_name_returns_english_for_en() -> None:
    """``'en'`` maps to ``'English'``."""
    assert language_name("en") == "English"


def test_language_name_unknown_falls_back_to_default() -> None:
    """Unknown codes fall back to the default language's name."""
    assert language_name("fr") == "English"
    assert language_name("") == "English"
    assert language_name("xx-YY") == "English"
