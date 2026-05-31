"""Interface string localization for the bot.

All user-facing messages, button labels, confirmations and error strings are
stored in per-language dictionaries and looked up through :func:`t`.

Usage::

    from bot.i18n import t

    text = t("task_saved", lang)
    text = t("reminder_snoozed", lang, period=label, formatted=when)

Resolution order:
    1. ``_STRINGS[lang][key]`` — the requested language's string.
    2. ``_STRINGS[DEFAULT_LANGUAGE][key]`` — English fallback when the requested
       language lacks the key.
    3. The literal ``key`` itself — defensive fallback so production never
       raises a ``KeyError`` on a missing translation; the raw key surfaces
       visibly in logs and UI so the gap is easy to spot.

Supported languages are ``ru`` and ``en``. The English table is treated as the
canonical/complete source: every key must exist there.
"""

from collections.abc import Mapping

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES: frozenset[str] = frozenset({"ru", "en"})

# Human-readable names for Claude prompts. Kept inside i18n because it is
# the canonical source of language identity in the project.
_LANGUAGE_NAMES: dict[str, str] = {
    "ru": "Russian",
    "en": "English",
}


def language_name(lang: str) -> str:
    """Return the English human-readable language name (e.g. ``'Russian'``) for a code.

    Used to interpolate the user's language into Claude prompts. Unknown or
    empty codes fall back to the default language's name so prompts never
    contain an empty placeholder.
    """
    return _LANGUAGE_NAMES.get(lang, _LANGUAGE_NAMES[DEFAULT_LANGUAGE])


# ---------------------------------------------------------------------------
# Russian translations
# ---------------------------------------------------------------------------
_RU: dict[str, str] = {
    # --- /start, /help, generic navigation ----------------------------------
    "welcome": (
        "Привет! Я твой умный инбокс.\n\n"
        "Просто пришли мне сообщение — я автоматически определю тип и сохраню:\n"
        "• <b>Ссылку</b> — сохраню и предложу саммари\n"
        "• <b>Задачу</b> — сохраню и предложу напоминание\n"
        "• <b>Идею</b> — сохраню с тегами и оценкой сложности\n"
        "• <b>Заметку</b> — просто сохраню на память\n\n"
        "<b>Команды:</b>\n"
        "/list — последние записи\n"
        "/search — поиск по сохранённому\n"
        "/reminders — предстоящие напоминания\n"
        "/ideas — банк идей\n"
        "/config — настройки (например, часовой пояс)\n"
        "/help — подробная справка\n"
        "/cancel — отмена текущего действия"
    ),
    "help_button_more": "Подробнее",
    "help_title": "<b>Подробная справка</b>\n",
    "help_content_types": (
        "<b>Типы контента</b>\n"
        "Отправь любое сообщение — бот определит тип автоматически:\n\n"
        "🔗 <b>Ссылка</b> — отправь URL, например:\n"
        "<code>https://example.com/interesting-article</code>\n"
        "Бот сохранит и предложит кнопки: Саммари, Сохранить, Напомнить.\n\n"
        "✅ <b>Задача</b> — напиши что нужно сделать, например:\n"
        "<code>купить молоко завтра</code>\n"
        "Бот предложит создать напоминание на нужное время.\n\n"
        "💡 <b>Идея</b> — напиши идею или концепцию, например:\n"
        "<code>а что если сделать бота для учёта расходов</code>\n"
        "Бот сохранит с тегами и оценкой сложности.\n"
        "Напиши <code>что поделать?</code> — бот предложит идею из банка.\n\n"
        "📝 <b>Заметка</b> — любой другой текст сохранится как заметка."
    ),
    "help_voice": (
        "🎤 <b>Голосовые сообщения</b>\nОтправь голосовое — бот расшифрует и обработает как текст."
    ),
    "help_media": (
        "🖼️ <b>Фото и файлы</b>\nОтправь фото или документ — бот загрузит в Google Drive."
    ),
    "help_reminders": (
        "<b>Напоминания</b>\n"
        "Когда напоминание сработает, появятся кнопки:\n"
        "⏰ +1ч — отложить на час\n"
        "🌙 +1д — отложить на день\n"
        "✅ Принято — отметить выполненным\n"
        "Если ни одна кнопка не нажата в течение 24 часов, бот автоматически "
        "пометит задачу как выполненную. Её всегда можно вернуть кнопкой "
        "«🔄 Реактивировать»."
    ),
    "help_commands": (
        "<b>Команды</b>\n"
        "/list — последние 10 записей с пагинацией\n"
        "/search — поиск по сохранённому (обычный или умный AI)\n"
        "/reminders — список предстоящих напоминаний\n"
        "/ideas — банк идей с тегами и сложностью\n"
        "/config — настройки (часовой пояс и т.д.)\n"
        "/help — эта справка\n"
        "/cancel — отмена текущего действия"
    ),
    "cancel_nothing_to_cancel": "Нет активного действия для отмены.",
    "cancel_done": "Отменено.",
    # --- Classifier / router fallbacks --------------------------------------
    "classifier_unavailable": "Сообщение получено. Классификация скоро будет доступна.",
    "unknown_type": "Тип: <b>{type}</b>. Полная обработка будет добавлена позже.",
    # --- Links --------------------------------------------------------------
    "link_saved": "🔗 Ссылка сохранена:\n{url}",
    "link_btn_summary": "📋 Саммари",
    "link_btn_save": "🔖 Сохранить",
    "link_btn_remind": "⏰ Напомнить",
    "link_btn_close": "✖️ Закрыть",
    "link_btn_retry": "🔄 Попробовать снова",
    "link_summary_loading": "🔗 {url}\n\n⏳ Загружаю саммари...",
    "link_summary_result": "🔗 {url}\n\n📋 <b>{title}</b>\n\n{body}",
    "link_scraping_failed": "🔗 {url}\n\n❌ Не удалось загрузить страницу.",
    "link_summary_failed": "🔗 {url}\n\n❌ Не удалось получить саммари.",
    "link_saved_confirmation": "🔖 <i>Сохранено</i>",
    "link_service_unavailable": "Сервис ссылок временно недоступен.",
    "embedding_unavailable_notice": (
        "ℹ️ Умный поиск временно недоступен, запись сохранена без индексации."
    ),
    # --- Tasks / reminders dialog ------------------------------------------
    "task_saved": "✅ Задача сохранена!",
    "task_btn_remind": "⏰ Напомнить",
    "task_saved_with_reminder": "✅ Задача сохранена!\n🔔 Напомню {formatted}!",
    "task_saved_reminder_failed": "✅ Задача сохранена, но не удалось создать напоминание.",
    "task_save_failed": "Не удалось сохранить задачу. Попробуй ещё раз.",
    "task_reminder_dialog_failed": (
        "Задача сохранена, но не удалось запустить диалог напоминания."
    ),
    "task_clarify_time": (
        "✅ Задача сохранена! Уточни время напоминания "
        "(или отправь то же выражение ещё раз):\n"
        "Для отмены — /cancel"
    ),
    "reminder_prompt_when": (
        "Когда напомнить? (например: «завтра в 10», «через 2 часа», «в пятницу в 15:00»)\n"
        "Для отмены — /cancel"
    ),
    "reminder_time_parse_failed_final": (
        "Не удалось разобрать время после нескольких попыток. Напоминание не создано."
    ),
    "reminder_time_parse_retry": (
        "Не смог понять время ({attempts}/{max_attempts}). "
        "Попробуй: «завтра в 10», «через 2 часа», «в пятницу в 15:00»\n"
        "Для отмены — /cancel"
    ),
    "reminder_save_failed": "Не удалось сохранить напоминание.",
    "reminder_created": "🔔 Напомню {formatted}!",
    "reminder_service_unavailable": "Сервис напоминаний временно недоступен.",
    "reminder_btn_snooze_1h": "⏰ +1ч",
    "reminder_btn_snooze_1d": "🌙 +1д",
    "reminder_btn_ack": "✅ Принято",
    "reminder_btn_cancel": "❌ Отменить",
    "reminder_btn_reactivate": "🔄 Реактивировать",
    "reminder_snooze_1h_label": "1 час",
    "reminder_snooze_1d_label": "1 день",
    "reminder_snoozed": "⏰ Напомню через {period} ({formatted}).",
    "reminder_snooze_failed": "Не удалось отложить напоминание.",
    "reminder_not_found_or_inactive": "Напоминание не найдено или уже неактивно.",
    "reminder_ack_failed": "Не удалось подтвердить напоминание.",
    "reminder_ack_done": "✅ <i>Выполнено</i>",
    "reminder_notification": "🔔 Напомню {formatted}\n{content}",
    "reminder_auto_completed": ("✅ Задача автоматически помечена как выполненная:\n{content}"),
    "reminder_reactivated_marker": "🔄 <i>Реактивировано</i>",
    "reminder_reactivate_failed": "Не удалось реактивировать напоминание.",
    "reminder_cancelled_marker": "✅ Напоминание отменено",
    "reminder_cancel_not_found": "Напоминание не найдено или уже отменено.",
    "reminder_cancel_invalid": "Неверный запрос.",
    # --- Ideas --------------------------------------------------------------
    "idea_saved": "💡 Идея сохранена!",
    "idea_save_failed": "Не удалось сохранить идею. Попробуй ещё раз.",
    "ideas_command_unavailable": "Команда /ideas скоро будет доступна.",
    "ideas_empty": "У тебя пока нет идей. Поделись — просто напиши идею!",
    "ideas_header": "💡 <b>Твои идеи</b> (стр. {page}):\n",
    "ideas_total": "\n<i>Всего: {total}</i>",
    "idea_complexity_simple": "простая",
    "idea_complexity_medium": "средняя",
    "idea_complexity_complex": "сложная",
    "idea_effort_quick": "< 1ч",
    "idea_effort_halfday": "1–4ч",
    "idea_effort_day": "4–8ч",
    "idea_effort_longterm": "долгосрочно",
    "idea_suggest_empty": ("У тебя пока нет сохранённых идей. Поделись идеей — просто напиши её!"),
    "idea_suggest_failed": "Не удалось сгенерировать подсказку. Попробуй ещё раз.",
    # --- Notes --------------------------------------------------------------
    "note_saved": "📝 Заметка сохранена!",
    "note_save_failed": "Не удалось сохранить заметку. Попробуй ещё раз.",
    # --- Media / photo / document -------------------------------------------
    "photo_received_disabled": "Фото получено. Обработка медиа скоро будет доступна.",
    "document_received_disabled": "Файл получен. Обработка медиа скоро будет доступна.",
    "photo_process_failed": "Не удалось обработать фото. Попробуй ещё раз.",
    "document_process_failed": "Не удалось обработать файл. Попробуй ещё раз.",
    "media_open_in_drive": "Открыть в Drive",
    "media_category_receipt": "Чек",
    "media_category_document": "Документ",
    "media_category_screenshot": "Скриншот",
    "media_category_photo": "Фото",
    "media_category_meme": "Мем",
    "media_category_other": "Другое",
    "vision_unsupported_format": "Формат файла не поддерживается для анализа.",
    "vision_analyze_failed": "Не удалось проанализировать файл.",
    "vision_media_default": "Медиафайл",
    # --- Voice --------------------------------------------------------------
    "voice_not_configured": (
        "Голосовые сообщения не настроены.\n"
        "Добавь <code>GROQ_API_KEY</code> в конфигурацию (бесплатно: console.groq.com)."
    ),
    "voice_transcribed": "🎤 Распознал: <i>«{text}»</i>",
    "voice_fallback_saved": "Голосовое сообщение сохранено!",
    "transcription_bad_key": "Неверный GROQ_API_KEY. Проверь ключ на console.groq.com.",
    "transcription_unavailable": "Сервис транскрипции недоступен. Попробуй позже.",
    "transcription_failed": "Не удалось распознать голосовое сообщение. Попробуй ещё раз.",
    # --- /list --------------------------------------------------------------
    "list_command_unavailable": "Команда /list скоро будет доступна.",
    "list_empty": (
        "У тебя пока ничего не сохранено.\nПришли ссылку, задачу, идею или фото — я запомню!"
    ),
    "list_header_all": "📋 <b>Последние записи</b> (стр. {page}):\n",
    "list_header_filtered": "📋 <b>{label}</b> (стр. {page}):\n",
    "list_total": "\n<i>Всего: {total}</i>",
    "list_filter_all": "Все",
    "list_filter_links": "🔗 Ссылки",
    "list_filter_tasks": "✅ Задачи",
    "list_filter_ideas": "💡 Идеи",
    "list_filter_notes": "📝 Заметки",
    "pagination_prev": "← Назад",
    "pagination_next": "Вперёд →",
    # --- /reminders ---------------------------------------------------------
    "reminders_command_unavailable": "Команда /reminders скоро будет доступна.",
    "reminders_empty": (
        "У тебя нет предстоящих напоминаний. "
        "Отправь задачу и выбери время, чтобы создать напоминание."
    ),
    "reminders_entry": "⏰ <b>{content}</b>\n🗓 {due}",
    # --- /search ------------------------------------------------------------
    "search_choose_mode": (
        "Какой поиск запустить?\n\n"
        "<b>🔍 Обычный</b> — ищет по точному вхождению текста.\n"
        "<b>🧠 Умный (AI)</b> — понимает смысл запроса, а не только слова."
    ),
    "search_btn_plain": "🔍 Обычный",
    "search_btn_smart": "🧠 Умный (AI)",
    "search_prompt_plain": "Введите запрос:",
    "search_prompt_smart": "Введите запрос для умного поиска:",
    "search_empty_query": "Пустой запрос. Введите текст или /cancel.",
    "search_service_unavailable": "Поиск временно недоступен. Попробуйте позже.",
    "search_semantic_unavailable": "Умный поиск временно недоступен. Попробуйте обычный поиск.",
    "search_no_results": "Ничего не найдено. Попробуйте перефразировать запрос.",
    "search_header_plain": "🔍 <b>Результаты по «{query}»</b> (стр. {page}):\n",
    "search_header_smart": "🧠 <b>Умный поиск по «{query}»</b> (стр. {page}):\n",
    "search_entry_relevance": "Релевантность: {bar}",
    "search_entry_preview": "Текст: {preview}",
    "search_label_link": "ссылка",
    "search_label_note": "заметка",
    "search_label_task": "задача",
    "search_label_media": "медиа",
    "search_label_idea": "идея",
    "search_label_record": "запись",
    # --- /config ------------------------------------------------------------
    "config_menu_title": "Настройки. Выбери, что хочешь изменить:",
    "config_unknown_setting": (
        "Неизвестная настройка. Отправь /config без аргументов, чтобы увидеть список."
    ),
    "config_btn_timezone": "🕐 Часовой пояс",
    "config_btn_language": "🌐 Язык",
    "language_choose": "Выбери язык интерфейса:",
    "language_btn_ru": "🇷🇺 Русский",
    "language_btn_en": "🇬🇧 English",
    "language_btn_current_mark": " ✓",
    "language_saved": "✅ Язык интерфейса установлен: <b>Русский</b>",
    "language_save_failed": "Не удалось сохранить выбранный язык. Попробуй ещё раз.",
    "language_settings_service_unavailable": (
        "Сервис настроек временно недоступен. Попробуй позже."
    ),
    # --- Timezone setup -----------------------------------------------------
    "tz_choose_continent": "Давай настроим твой часовой пояс. Выбери континент:",
    "tz_no_zones_on_continent": ("Для этого континента нет доступных зон. Попробуй другой."),
    "tz_choose_country": "Континент: <b>{continent}</b>\nТеперь выбери страну:",
    "tz_choose_city": "Страна: <b>{country}</b>\nВыбери город / часовой пояс:",
    "tz_settings_service_unavailable": ("Сервис настроек временно недоступен. Попробуй позже."),
    "tz_save_failed": "Не удалось сохранить выбранный часовой пояс. Попробуй ещё раз.",
    "tz_saved": "✅ Часовой пояс установлен: <b>{zone}</b> ({offset})",
    "tz_continent_europe": "Европа",
    "tz_continent_asia": "Азия",
    "tz_continent_america": "Америка",
    "tz_continent_other": "Другое",
    # --- /reindex -----------------------------------------------------------
    "reindex.all.in_progress": (
        "🔄 Найдено {count} записей без индексации. Запускаю переиндексацию..."
    ),
    "reindex.all.in_progress_truncated_suffix": " (будут обработаны первые 200)",
    "reindex.all.already_indexed": "✅ Все твои записи уже проиндексированы.",
    "reindex.all.unavailable": (
        "ℹ️ Умный поиск временно недоступен. Попробуй переиндексацию позже."
    ),
    "reindex.all.not_configured": "ℹ️ Умный поиск не настроен в этом инстансе бота.",
    "reindex.all.already_running": ("ℹ️ Переиндексация уже выполняется, дождись окончания."),
    "reindex.all.done": "✅ Готово. Проиндексировано: {succeeded}.",
    "reindex.all.done_with_failures_suffix": (
        " Не удалось: {failed} (умный поиск был недоступен)."
    ),
    "reindex.all.done_truncated_suffix": ("Осталось ещё записей — запусти /reindex повторно."),
    "reindex.button.try_again": "🔄 Попробовать ещё раз",
    "reindex.one.success": "✅ Запись проиндексирована, теперь её найдёт умный поиск.",
    "reindex.one.still_unavailable": "ℹ️ Умный поиск всё ещё недоступен, попробуй позже.",
    "reindex.one.already_indexed": "Запись уже проиндексирована.",
    "reindex.one.not_yours": "Это не твоя запись.",
    "commands.reindex.description": "🔄 Переиндексировать записи",
    # --- Bot commands menu (shown by Telegram clients) ----------------------
    "botcmd_start": "Начать работу",
    "botcmd_list": "Последние записи",
    "botcmd_search": "Поиск по записям",
    "botcmd_reminders": "Предстоящие напоминания",
    "botcmd_ideas": "Мои идеи",
    "botcmd_config": "Настройки",
    "botcmd_cancel": "Отменить текущее действие",
}


# ---------------------------------------------------------------------------
# English translations
# ---------------------------------------------------------------------------
_EN: dict[str, str] = {
    # --- /start, /help, generic navigation ----------------------------------
    "welcome": (
        "Hi! I'm your smart inbox.\n\n"
        "Just send me any message — I'll detect the type and save it automatically:\n"
        "• <b>Link</b> — I'll save it and offer a summary\n"
        "• <b>Task</b> — I'll save it and offer a reminder\n"
        "• <b>Idea</b> — I'll save it with tags and a complexity score\n"
        "• <b>Note</b> — I'll just save it for later\n\n"
        "<b>Commands:</b>\n"
        "/list — latest records\n"
        "/search — search saved content\n"
        "/reminders — upcoming reminders\n"
        "/ideas — idea bank\n"
        "/config — settings (e.g. timezone)\n"
        "/help — detailed help\n"
        "/cancel — cancel the current action"
    ),
    "help_button_more": "More",
    "help_title": "<b>Detailed help</b>\n",
    "help_content_types": (
        "<b>Content types</b>\n"
        "Send any message — the bot will detect its type automatically:\n\n"
        "🔗 <b>Link</b> — send a URL, e.g.:\n"
        "<code>https://example.com/interesting-article</code>\n"
        "The bot will save it and offer: Summary, Save, Remind.\n\n"
        "✅ <b>Task</b> — write what needs to be done, e.g.:\n"
        "<code>buy milk tomorrow</code>\n"
        "The bot will offer to create a reminder at the right time.\n\n"
        "💡 <b>Idea</b> — write an idea or concept, e.g.:\n"
        "<code>what if I made a bot to track expenses</code>\n"
        "The bot will save it with tags and a complexity score.\n"
        "Write <code>what should I do?</code> — the bot will suggest an idea from the bank.\n\n"
        "📝 <b>Note</b> — any other text is saved as a note."
    ),
    "help_voice": (
        "🎤 <b>Voice messages</b>\n"
        "Send a voice message — the bot will transcribe and process it as text."
    ),
    "help_media": (
        "🖼️ <b>Photos and files</b>\nSend a photo or document — the bot will upload it to Google Drive."
    ),
    "help_reminders": (
        "<b>Reminders</b>\n"
        "When a reminder fires, these buttons appear:\n"
        "⏰ +1h — snooze for an hour\n"
        "🌙 +1d — snooze for a day\n"
        "✅ Done — mark as acknowledged\n"
        "If no button is pressed within 24 hours, the bot will automatically "
        "mark the task as done. You can always bring it back with the "
        "🔄 Reactivate button."
    ),
    "help_commands": (
        "<b>Commands</b>\n"
        "/list — the last 10 records with pagination\n"
        "/search — search saved content (plain or smart AI)\n"
        "/reminders — list of upcoming reminders\n"
        "/ideas — idea bank with tags and complexity\n"
        "/config — settings (timezone, etc.)\n"
        "/help — this help\n"
        "/cancel — cancel the current action"
    ),
    "cancel_nothing_to_cancel": "There's no active action to cancel.",
    "cancel_done": "Cancelled.",
    # --- Classifier / router fallbacks --------------------------------------
    "classifier_unavailable": "Message received. Classification will be available soon.",
    "unknown_type": "Type: <b>{type}</b>. Full handling will be added later.",
    # --- Links --------------------------------------------------------------
    "link_saved": "🔗 Link saved:\n{url}",
    "link_btn_summary": "📋 Summary",
    "link_btn_save": "🔖 Save",
    "link_btn_remind": "⏰ Remind",
    "link_btn_close": "✖️ Close",
    "link_btn_retry": "🔄 Retry",
    "link_summary_loading": "🔗 {url}\n\n⏳ Loading summary...",
    "link_summary_result": "🔗 {url}\n\n📋 <b>{title}</b>\n\n{body}",
    "link_scraping_failed": "🔗 {url}\n\n❌ Failed to load the page.",
    "link_summary_failed": "🔗 {url}\n\n❌ Failed to produce a summary.",
    "link_saved_confirmation": "🔖 <i>Saved</i>",
    "link_service_unavailable": "The link service is temporarily unavailable.",
    "embedding_unavailable_notice": (
        "ℹ️ Smart search is temporarily unavailable — the record was saved without indexing."
    ),
    # --- Tasks / reminders dialog ------------------------------------------
    "task_saved": "✅ Task saved!",
    "task_btn_remind": "⏰ Remind",
    "task_saved_with_reminder": "✅ Task saved!\n🔔 I'll remind you {formatted}!",
    "task_saved_reminder_failed": "✅ Task saved, but failed to create the reminder.",
    "task_save_failed": "Failed to save the task. Try again.",
    "task_reminder_dialog_failed": "Task saved, but failed to start the reminder dialog.",
    "task_clarify_time": (
        "✅ Task saved! Please clarify the reminder time "
        "(or just send the same expression again):\n"
        "To cancel — /cancel"
    ),
    "reminder_prompt_when": (
        'When should I remind you? (e.g. "tomorrow at 10", "in 2 hours", "on Friday at 15:00")\n'
        "To cancel — /cancel"
    ),
    "reminder_time_parse_failed_final": (
        "Couldn't parse the time after several attempts. No reminder was created."
    ),
    "reminder_time_parse_retry": (
        "Couldn't understand the time ({attempts}/{max_attempts}). "
        'Try: "tomorrow at 10", "in 2 hours", "on Friday at 15:00"\n'
        "To cancel — /cancel"
    ),
    "reminder_save_failed": "Failed to save the reminder.",
    "reminder_created": "🔔 I'll remind you {formatted}!",
    "reminder_service_unavailable": "The reminder service is temporarily unavailable.",
    "reminder_btn_snooze_1h": "⏰ +1h",
    "reminder_btn_snooze_1d": "🌙 +1d",
    "reminder_btn_ack": "✅ Done",
    "reminder_btn_cancel": "❌ Cancel",
    "reminder_btn_reactivate": "🔄 Reactivate",
    "reminder_snooze_1h_label": "1 hour",
    "reminder_snooze_1d_label": "1 day",
    "reminder_snoozed": "⏰ I'll remind you in {period} ({formatted}).",
    "reminder_snooze_failed": "Failed to snooze the reminder.",
    "reminder_not_found_or_inactive": "Reminder not found or already inactive.",
    "reminder_ack_failed": "Failed to acknowledge the reminder.",
    "reminder_ack_done": "✅ <i>Done</i>",
    "reminder_notification": "🔔 Reminder {formatted}\n{content}",
    "reminder_auto_completed": ("✅ Task automatically marked as done:\n{content}"),
    "reminder_reactivated_marker": "🔄 <i>Reactivated</i>",
    "reminder_reactivate_failed": "Failed to reactivate the reminder.",
    "reminder_cancelled_marker": "✅ Reminder cancelled",
    "reminder_cancel_not_found": "Reminder not found or already cancelled.",
    "reminder_cancel_invalid": "Invalid request.",
    # --- Ideas --------------------------------------------------------------
    "idea_saved": "💡 Idea saved!",
    "idea_save_failed": "Failed to save the idea. Try again.",
    "ideas_command_unavailable": "The /ideas command will be available soon.",
    "ideas_empty": "You don't have any ideas yet. Share one — just write it down!",
    "ideas_header": "💡 <b>Your ideas</b> (page {page}):\n",
    "ideas_total": "\n<i>Total: {total}</i>",
    "idea_complexity_simple": "simple",
    "idea_complexity_medium": "medium",
    "idea_complexity_complex": "complex",
    "idea_effort_quick": "< 1h",
    "idea_effort_halfday": "1–4h",
    "idea_effort_day": "4–8h",
    "idea_effort_longterm": "long-term",
    "idea_suggest_empty": ("You don't have any saved ideas yet. Share one — just write it down!"),
    "idea_suggest_failed": "Failed to generate a suggestion. Try again.",
    # --- Notes --------------------------------------------------------------
    "note_saved": "📝 Note saved!",
    "note_save_failed": "Failed to save the note. Try again.",
    # --- Media / photo / document -------------------------------------------
    "photo_received_disabled": "Photo received. Media processing will be available soon.",
    "document_received_disabled": "File received. Media processing will be available soon.",
    "photo_process_failed": "Failed to process the photo. Try again.",
    "document_process_failed": "Failed to process the file. Try again.",
    "media_open_in_drive": "Open in Drive",
    "media_category_receipt": "Receipt",
    "media_category_document": "Document",
    "media_category_screenshot": "Screenshot",
    "media_category_photo": "Photo",
    "media_category_meme": "Meme",
    "media_category_other": "Other",
    "vision_unsupported_format": "This file format is not supported for analysis.",
    "vision_analyze_failed": "Failed to analyze the file.",
    "vision_media_default": "Media file",
    # --- Voice --------------------------------------------------------------
    "voice_not_configured": (
        "Voice messages are not configured.\n"
        "Add <code>GROQ_API_KEY</code> to the configuration (free: console.groq.com)."
    ),
    "voice_transcribed": "🎤 Transcribed: <i>«{text}»</i>",
    "voice_fallback_saved": "Voice message saved!",
    "transcription_bad_key": "Invalid GROQ_API_KEY. Check the key at console.groq.com.",
    "transcription_unavailable": "Transcription service is unavailable. Try later.",
    "transcription_failed": "Failed to transcribe the voice message. Try again.",
    # --- /list --------------------------------------------------------------
    "list_command_unavailable": "The /list command will be available soon.",
    "list_empty": (
        "You don't have anything saved yet.\nSend a link, task, idea or photo — I'll remember it!"
    ),
    "list_header_all": "📋 <b>Latest records</b> (page {page}):\n",
    "list_header_filtered": "📋 <b>{label}</b> (page {page}):\n",
    "list_total": "\n<i>Total: {total}</i>",
    "list_filter_all": "All",
    "list_filter_links": "🔗 Links",
    "list_filter_tasks": "✅ Tasks",
    "list_filter_ideas": "💡 Ideas",
    "list_filter_notes": "📝 Notes",
    "pagination_prev": "← Back",
    "pagination_next": "Next →",
    # --- /reminders ---------------------------------------------------------
    "reminders_command_unavailable": "The /reminders command will be available soon.",
    "reminders_empty": (
        "You have no upcoming reminders. Send a task and pick a time to create one."
    ),
    "reminders_entry": "⏰ <b>{content}</b>\n🗓 {due}",
    # --- /search ------------------------------------------------------------
    "search_choose_mode": (
        "Which search should I run?\n\n"
        "<b>🔍 Plain</b> — matches exact text occurrences.\n"
        "<b>🧠 Smart (AI)</b> — understands the meaning, not just words."
    ),
    "search_btn_plain": "🔍 Plain",
    "search_btn_smart": "🧠 Smart (AI)",
    "search_prompt_plain": "Enter a query:",
    "search_prompt_smart": "Enter a smart-search query:",
    "search_empty_query": "Empty query. Enter text or /cancel.",
    "search_service_unavailable": "Search is temporarily unavailable. Try later.",
    "search_semantic_unavailable": "Smart search is temporarily unavailable. Try plain search.",
    "search_no_results": "Nothing found. Try rephrasing your query.",
    "search_header_plain": "🔍 <b>Results for «{query}»</b> (page {page}):\n",
    "search_header_smart": "🧠 <b>Smart search for «{query}»</b> (page {page}):\n",
    "search_entry_relevance": "Relevance: {bar}",
    "search_entry_preview": "Text: {preview}",
    "search_label_link": "link",
    "search_label_note": "note",
    "search_label_task": "task",
    "search_label_media": "media",
    "search_label_idea": "idea",
    "search_label_record": "record",
    # --- /config ------------------------------------------------------------
    "config_menu_title": "Settings. Choose what you want to change:",
    "config_unknown_setting": ("Unknown setting. Send /config without arguments to see the list."),
    "config_btn_timezone": "🕐 Timezone",
    "config_btn_language": "🌐 Language",
    "language_choose": "Choose the interface language:",
    "language_btn_ru": "🇷🇺 Русский",
    "language_btn_en": "🇬🇧 English",
    "language_btn_current_mark": " ✓",
    "language_saved": "✅ Interface language set to: <b>English</b>",
    "language_save_failed": "Failed to save the selected language. Try again.",
    "language_settings_service_unavailable": (
        "The settings service is temporarily unavailable. Try later."
    ),
    # --- Timezone setup -----------------------------------------------------
    "tz_choose_continent": "Let's set up your timezone. Choose a continent:",
    "tz_no_zones_on_continent": ("No available zones for this continent. Try another one."),
    "tz_choose_country": "Continent: <b>{continent}</b>\nNow choose a country:",
    "tz_choose_city": "Country: <b>{country}</b>\nChoose a city / timezone:",
    "tz_settings_service_unavailable": (
        "The settings service is temporarily unavailable. Try later."
    ),
    "tz_save_failed": "Failed to save the selected timezone. Try again.",
    "tz_saved": "✅ Timezone set: <b>{zone}</b> ({offset})",
    "tz_continent_europe": "Europe",
    "tz_continent_asia": "Asia",
    "tz_continent_america": "America",
    "tz_continent_other": "Other",
    # --- /reindex -----------------------------------------------------------
    "reindex.all.in_progress": ("🔄 Found {count} items without indexing. Starting re-indexing..."),
    "reindex.all.in_progress_truncated_suffix": " (the first 200 will be processed)",
    "reindex.all.already_indexed": "✅ All your items are already indexed.",
    "reindex.all.unavailable": (
        "ℹ️ Smart search is temporarily unavailable. Try re-indexing later."
    ),
    "reindex.all.not_configured": "ℹ️ Smart search is not configured in this bot instance.",
    "reindex.all.already_running": ("ℹ️ Re-indexing is already running, wait for it to finish."),
    "reindex.all.done": "✅ Done. Indexed: {succeeded}.",
    "reindex.all.done_with_failures_suffix": (" Failed: {failed} (smart search was unavailable)."),
    "reindex.all.done_truncated_suffix": ("There are more items left — run /reindex again."),
    "reindex.button.try_again": "🔄 Try again",
    "reindex.one.success": "✅ Item indexed, smart search will find it now.",
    "reindex.one.still_unavailable": "ℹ️ Smart search is still unavailable, try later.",
    "reindex.one.already_indexed": "Item is already indexed.",
    "reindex.one.not_yours": "This is not your item.",
    "commands.reindex.description": "🔄 Re-index items",
    # --- Bot commands menu (shown by Telegram clients) ----------------------
    "botcmd_start": "Start",
    "botcmd_list": "Latest records",
    "botcmd_search": "Search records",
    "botcmd_reminders": "Upcoming reminders",
    "botcmd_ideas": "My ideas",
    "botcmd_config": "Settings",
    "botcmd_cancel": "Cancel the current action",
}


# Frozen at import time — outside code must go through :func:`t`.
_STRINGS: Mapping[str, Mapping[str, str]] = {
    "ru": _RU,
    "en": _EN,
}


def t(key: str, lang: str, **kwargs: object) -> str:
    """Return the localized string for ``key`` in ``lang``, with fallbacks.

    ``kwargs`` are passed to :py:meth:`str.format` so templates can use named
    placeholders like ``{formatted}``. If the key is missing in the requested
    language, fall back to English; if it is missing there too, return the raw
    key so the gap is visible instead of crashing.
    """
    table = _STRINGS.get(lang) or _STRINGS[DEFAULT_LANGUAGE]
    template = table.get(key)
    if template is None:
        template = _STRINGS[DEFAULT_LANGUAGE].get(key, key)
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        # Malformed template or missing placeholder — return the unformatted
        # string rather than raising, so a typo in a caller never blocks a reply.
        return template
