# Architecture Guide — tg-smart-inbox

## Overview

`tg-smart-inbox` is a Telegram bot that works as a smart personal inbox. The user forwards
or sends any content — links, tasks, ideas, voice messages, photos, files — and the bot
classifies it automatically using Claude AI, saves it to a database, and provides tools
to work with the saved content.

**Tech stack:**
- Python 3.11+
- [aiogram 3.x](https://docs.aiogram.dev/) — async Telegram Bot API framework
- SQLAlchemy async + Alembic — database ORM and migrations
- [Anthropic Claude API](https://docs.anthropic.com/) — AI classification and summarization
- APScheduler — background job scheduling
- Groq Whisper API — voice transcription (optional)
- Google Drive API — media file upload (optional)

---

## 3-Layer Architecture

All code follows a strict 3-layer pattern:

```
Telegram Update
     │
     ▼
┌─────────────┐
│   Handler   │  bot/handlers/   — thin layer: validates input, calls services, replies
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Service   │  bot/services/   — business logic, AI calls, transaction boundaries
└──────┬──────┘
       │
       ▼
┌──────────────┐
│  Repository  │  bot/repositories/  — SQLAlchemy queries, flush/refresh only
└──────────────┘
       │
       ▼
  PostgreSQL / SQLite
```

### Handlers (`bot/handlers/`)

Handlers are the thinnest layer. They:
- Receive Telegram events (messages, callback queries)
- Call one or more services
- Send a response to the user

Handlers **never** contain business logic, direct DB access, or external API calls.

| File | Responsibility |
|------|---------------|
| `messages.py` | Entry point for all incoming text, photo, and document messages |
| `links.py` | Callback buttons for saved links (summary, save, remind) |
| `reminders.py` | Reminder dialog (`ReminderStates.waiting_for_time` FSM), snooze/acknowledge callbacks, custom snooze dialog (`CustomSnoozeStates.waiting_for_custom_time` FSM entered via the «⏰ Other...» button) |
| `commands.py` | Bot commands: `/start`, `/list`, `/reminders`, `/ideas`, `/reindex`, `/help`, `/cancel` |
| `config.py` | `/config` command — extensible settings menu; currently dispatches to the timezone FSM |
| `ideas.py` | `/ideas` command — display saved ideas |
| `search.py` | `/search` command — FSM for picking search mode (plain / semantic) + paginated results |
| `voice.py` | Voice message transcription and routing |
| `timezone_setup.py` | Three-step inline FSM for picking a timezone (continent → country → city) |
| `reindex.py` | Single-record retry button under the embedding-unavailable notice (`🔄 Попробовать ещё раз`); routes `reindex:item:<uuid>` / `reindex:idea:<uuid>` callbacks to `ReindexService` |

### Services (`bot/services/`)

Services contain all business logic. They call repositories and external APIs. Services
own transaction boundaries — they call `session.commit()` after all repository calls succeed.

| File | Responsibility |
|------|---------------|
| `classifier.py` | Classify incoming messages: LINK / TASK / NOTE / IDEA / MEDIA |
| `claude_client.py` | Thin wrapper around the Anthropic API |
| `embedding_service.py` | Generate vector embeddings for Items and Ideas; gracefully returns `None` on API error; exposes `is_configured` so callers can distinguish "Voyage AI key absent" from "transient outage" |
| `link_service.py` | Save links to DB (with cached page text, extracted page title, and AI-generated summary persisted at save time); reuse stored summary or scraped-text cache when generating on-demand summaries |
| `reminder_service.py` | Create, cancel, snooze, acknowledge, mark auto-completed, reactivate reminders, and reset `auto_archive_at` (used when the custom snooze FSM is entered) |
| `time_parser.py` | Parse natural-language time expressions using Claude (timezone-aware) |
| `idea_service.py` | Save ideas with AI-extracted tags, complexity/effort, and suggestions |
| `task_service.py` | Save tasks to DB |
| `note_service.py` | Save notes to DB |
| `list_service.py` | Paginated item listing and full-text search |
| `semantic_search_service.py` | Cosine-similarity search over Item and Idea embeddings via pgvector |
| `reindex_service.py` | Regenerate missing embeddings for one user — single record (`reindex_item` / `reindex_idea`), bulk pass (`reindex_all_for_user`), and pre-run backlog count (`count_unindexed_for_user`); throttles Voyage AI to one call per 100 ms and caps each run at 200 records |
| `media_service.py` | Process photos/files: vision categorization + Drive upload |
| `drive_service.py` | Google Drive API wrapper |
| `scraper.py` | HTTP page fetcher for link summarization; extracts `og:title` / `<title>` alongside the body text |
| `transcription_service.py` | Groq Whisper API wrapper for voice messages |
| `vision_service.py` | Claude Vision API for image description |
| `user_settings_service.py` | Read/write per-user preferences (timezone, language) with IANA / supported-language validation |

### Repositories (`bot/repositories/`)

Repositories are the only layer that holds an `AsyncSession` and runs SQLAlchemy queries.
They call `flush()` and `refresh()` but **never** `commit()` — the service layer owns
the transaction boundary.

| File | Responsibility |
|------|---------------|
| `item_repository.py` | CRUD for `Item` records |
| `reminder_repository.py` | CRUD for `Reminder` records, due/auto-archive queries, reactivate |
| `idea_repository.py` | CRUD for `Idea` records |
| `user_settings.py` | CRUD for `UserSettings` records (per-user preferences) |

---

## Database Schema

### `items` table

The central table that stores every piece of content the user saves.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID (PK) | Auto-generated UUID |
| `created_at` | DateTime | Creation timestamp (UTC) |
| `user_id` | BigInteger | Telegram user ID |
| `type` | Enum | `link`, `note`, `task`, `media`, `idea` |
| `content` | Text | The actual content (URL, text, file path, etc.) |
| `description` | Text (nullable) | Optional description (used for media) |
| `title` | Text (nullable) | Article title for links (`og:title` → `<title>` → `None`); used by `/list`, `/search`, `/reminders` and reminder push notifications to render `{title} ({url})` instead of the bare URL |
| `scraped_text` | Text (nullable) | Cached full page text for links (used to re-embed without re-scraping) |
| `summary` | Text (nullable) | AI-generated summary for links — persisted at save time and shown inline in reminder notifications; `NULL` for older records and non-link items |
| `embedding` | `vector(1024)` (nullable) | pgvector embedding for semantic search; ivfflat/cosine index |

### `reminders` table

One reminder per item (can have multiple per item after snooze cycles).

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID (PK) | Auto-generated UUID |
| `item_id` | UUID (FK → items) | The item being reminded about |
| `remind_at` | DateTime (TZ) | Scheduled notification time |
| `is_sent` | Boolean | Whether the reminder was dispatched |
| `is_cancelled` | Boolean | Whether the user cancelled it |
| `is_acknowledged` | Boolean | Whether the user pressed "Принято" |
| `is_auto_completed` | Boolean | Whether the 24h auto-archive job closed the reminder (set by `_auto_archive_reminders`; cleared on reactivate) |
| `snooze_count` | Integer | How many times this reminder was snoozed |
| `auto_archive_at` | DateTime (nullable) | When to auto-archive if no button was pressed (set to `now + 24h` on delivery; cleared on acknowledge / snooze / cancel / auto-archive completion / reactivate) |

Reminder status is encoded as four mutually-recoverable boolean flags rather
than an enum so each transition (deliver → snooze → ack → auto-complete →
reactivate) maps to a single column update. The migration that introduced the
24h flow (`f1a2c3d4e5b6`) renamed the legacy `auto_resend_at` column to
`auto_archive_at` and added `is_auto_completed`.

### `ideas` table

Additional metadata for items with `type = idea`.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID (PK) | Auto-generated UUID |
| `item_id` | UUID (FK → items, unique) | The parent item |
| `tags` | JSON (list of str) | AI-extracted tags (max 5, max 30 chars each) |
| `complexity` | Enum (nullable) | `simple`, `medium`, `complex` |
| `effort` | Enum (nullable) | `quick` (<1h), `halfday` (1-4h), `day` (4-8h), `longterm` |
| `embedding` | `vector(1024)` (nullable) | pgvector embedding for idea-level semantic search; ivfflat/cosine index |

### pgvector extension

Semantic search uses the [pgvector](https://github.com/pgvector/pgvector) PostgreSQL
extension. The initial migration (`98444ad48da7`) adds the `embedding` columns and
indexes; migration `c3e7f2a1d8b4` resizes them from `vector(1536)` to `vector(1024)`
to match the Voyage AI model output. Migration `e9a4d2b6c815` adds the nullable `items.title` column used to display
article headlines instead of bare URLs. Migration `a1b2c3d4e5f6` adds the
nullable `items.summary` column that stores the AI-generated link summary
persisted at save time and shown inline in reminder notifications.
Both `items` and `ideas` carry an `ivfflat` index with `vector_cosine_ops` (100 lists).

On SQLite (used only in tests) the migration and ORM still create the columns, but
the extension and the vector index are skipped because pgvector is PostgreSQL-only.
The dimensionality is exposed via the `EMBEDDING_DIM` config field (default `1024`,
matching `voyage-3.5`); changing it requires a new Alembic migration since vector
columns have a fixed size.

### `user_settings` table

Per-user preferences. One row per Telegram user; created lazily on first write.

| Column | Type | Description |
|--------|------|-------------|
| `user_id` | BigInteger (PK) | Telegram user ID |
| `timezone` | String(64) | IANA tz name (e.g. `Europe/Moscow`); NOT NULL, default `UTC` |
| `language` | String(8) | Interface language — `ru` or `en`; NOT NULL, default `en` |
| `created_at` | DateTime (TZ) | Row creation timestamp |
| `updated_at` | DateTime (TZ) | Last update timestamp (auto-bumped on UPDATE) |

On first creation the language is derived from Telegram's `language_code` field:
codes starting with `ru` (case-insensitive) yield `ru`, everything else yields the
default `en`. The derivation lives in `UserSettingsService.ensure_user_settings()`.
Once a row exists, subsequent calls to `ensure_user_settings()` never overwrite the
stored language — the user-set value wins over Telegram locale drift.

`UserSettingsService` exposes `get_language(user_id)`, `set_language(user_id, lang)`
(raises `InvalidLanguageError` for anything outside `{"ru", "en"}`), and
`ensure_user_settings(user_id, language_code)`. The repository provides
`set_language()` and a `get_or_create()` that accepts an initial `language` kwarg.

### Interface string localization (`bot/i18n.py`)

All user-facing interface strings — confirmations, button labels, reminder
notifications, error messages, and the text for `/list`, `/search`, `/ideas`,
`/reminders`, `/config` — live in a single module, `bot/i18n.py`, and are looked
up through `t(key: str, lang: str, **kwargs) -> str`. Two dictionaries,
`_RU` and `_EN`, hold the translations; both are kept in sync (tests enforce
that every key exists in both). `kwargs` are passed to `str.format` so callers
can interpolate values like `{formatted}`, `{content}`, or `{query}`.

Resolution order in `t()`:

1. Look up the key in the requested language's table.
2. Fall back to English (`DEFAULT_LANGUAGE`) if the key is missing there.
3. As a last resort return the raw key — so a typo surfaces visibly in logs/UI
   rather than raising `KeyError` in production.

The per-user language is read from `UserSettingsService.get_language()` at the
handler layer; handlers pass it into `t()` when rendering a reply. The i18n
module itself is pure: it has no I/O, no session, no external calls.

---

## Dependency Injection

All services and the DB session are injected into handlers via `DependencyMiddleware`
(`bot/middleware.py`). The middleware runs on every Telegram update:

1. Opens an `AsyncSession` from the session factory
2. Instantiates all repositories and services
3. Puts them in the aiogram `data` dict
4. Calls the handler
5. Closes the session

```
DependencyMiddleware.__call__()
  ├── opens session
  ├── creates: ClaudeClient, EmbeddingService, ItemRepository,
  │            ReminderRepository, IdeaRepository
  ├── injects: classifier, embedding_service, link_service, reminder_service,
  │            time_parser, idea_service, task_service, note_service,
  │            list_service, semantic_search_service, reindex_service,
  │            user_settings_service
  ├── if GROQ_API_KEY: injects transcription_service (else None)
  ├── if GOOGLE_DRIVE_FOLDER_ID: injects media_service (else None)
  └── calls handler
```

Handlers declare injected dependencies as keyword arguments:

```python
async def handle_text(message: Message, classifier: ClassifierService | None = None) -> None:
    ...
```

Optional services (`transcription_service`, `media_service`) are injected as `None` when
their external credentials are not configured. Handlers check for `None` and respond with
a user-friendly message.

---

## Message Routing Pipeline

When a text message arrives, `handle_text` in `bot/handlers/messages.py` routes it:

```
Incoming text message
        │
        ▼
Has a URL? ──yes──► LINK pipeline
        │
        ▼
Is a suggestion query? ──yes──► idea_service.suggest()
        │
        ▼
classifier.classify(text)  [Claude API call]
        │
   ┌────┴────┐
   │  type?  │
   └────┬────┘
        ├── LINK  ──► link_service.save() → show action keyboard
        ├── IDEA  ──► idea_service.save_idea() → show tags/complexity
        ├── TASK  ──► task_service.save()
        │              ├── no time expression → "Задача сохранена!" + кнопка «⏰ Напомнить»
        │              └── has time expression → time_parser.parse()
        │                     ├── success → reminder_service.create() → "🔔 Напомню <time>!"
        │                     └── parse fail → FSM waiting_for_time (manual input)
        └── NOTE  ──► note_service.save() → "Заметка сохранена!"
```

Voice messages (`bot/handlers/voice.py`) follow the same pipeline after transcription
via `TranscriptionService` (Groq Whisper).

Photo and document messages go directly to `MediaService` (Vision + Drive upload)
without classification.

---

## Classifier

`ClassifierService` (`bot/services/classifier.py`) uses a two-step approach:

1. **Fast rules (no API call):**
   - Message has media → `MEDIA`
   - Message contains a URL (`https?://...`) → `LINK`

2. **Claude API:** For all other text, sends a prompt asking Claude to classify into
   `task`, `idea`, or `note`. Returns a JSON response `{"type": "task"}`.

Claude sometimes wraps JSON in markdown code fences (` ```json ... ``` `).
The classifier strips them before parsing.

---

## Google Drive

`DriveService` (`bot/services/drive_service.py`) wraps the Google Drive v3 API
and is the only service that uploads files. It is constructed once per request
by `DependencyMiddleware`, but its OAuth credentials and authenticated
`googleapiclient` service are loaded lazily inside `_ensure_service()` on the
first upload (so cold-start handlers that don't touch Drive aren't penalised).

### Folder layout

Each Telegram user gets their own subtree under `GOOGLE_DRIVE_FOLDER_ID`:

```
{GOOGLE_DRIVE_FOLDER_ID}/
├── user_{user_id_a}/
│   ├── 📄 Receipts/
│   ├── 📁 Documents/
│   ├── 🖥️ Screenshots/
│   ├── 🖼️ Photos/
│   ├── 😄 Memes/
│   └── 📦 Other/
├── user_{user_id_b}/
│   └── ...
```

`upload_file(file_bytes, filename, category, user_id)` resolves
(or creates) two folders before uploading:

1. The per-user root `user_{user_id}` directly under `GOOGLE_DRIVE_FOLDER_ID`.
2. The category folder (`📄 Receipts`, `🖼️ Photos`, …) under that user root.
   Unknown categories fall back to `📦 Other`.

Both lookups are idempotent: if a folder with the target name already exists
under the right parent, its existing ID is reused. This isolates files between
Telegram users and gives each user a self-contained Drive view.

### Folder ID cache

`DriveService._folder_cache` is an in-memory `dict[tuple[int, str], str]`
keyed by `(user_id, category)`, with a special `(user_id, "__user_root__")`
entry storing the per-user root ID. The cache is populated on first lookup and
short-circuits subsequent folder lookups within the same request — no
`files.list` or `files.create` round trips, just the file upload itself.

The cache lives on the `DriveService` instance, and `DependencyMiddleware`
constructs a fresh `DriveService` for every incoming update (see
`bot/middleware.py`). As a result the cache is **scoped to a single request**
and is discarded once the handler returns. In practice this still helps when a
single message produces multiple Drive uploads (e.g. a media group), but it
does not persist across messages. Promoting `DriveService` to a long-lived
singleton so the cache survives across requests is tracked as a separate
follow-up task.

### Multi-user model (v1)

The v1 model uses a **single bot-owner Google Drive integration**:

- One OAuth token (`token.json`) authenticates the bot against Drive on behalf
  of the bot operator's Google account.
- All users' files share that single Drive quota.
- Isolation is enforced at the folder level only — each Telegram user gets
  their own `user_{telegram_id}` subtree (see folder layout above). The numeric
  Telegram ID is used as the folder name; no display name or other PII appears
  in Drive paths.
- The bot operator can see all users' subfolders in the shared Drive root.
  No per-user visibility controls exist in v1.

### Deferred v2 items

The following Drive capabilities are **explicitly out of scope for v1** and
tracked as future work:

- **Per-user Google OAuth credentials** — each Telegram user authenticates
  with their own Google account so files land in their personal Drive.
- **Per-user upload quotas / rate limiting** — prevent one user from
  exhausting the shared quota.
- **Admin visibility controls** — restrict the bot operator's view of
  individual users' subfolders.

### Failure modes

- Missing or empty `token.json` → `DriveUploadError` with a hint to run
  `scripts/drive_auth.py`.
- Token refresh failure (network down, revoked refresh token) →
  `DriveUploadError` wrapping the original exception.
- Any Drive API error during upload (including quota exhaustion /
  `rateLimitExceeded`) → `DriveUploadError` raised by `upload_file`.
  The handler (`handle_photo` / `handle_document`) catches `DriveUploadError`
  and replies with a user-facing error message; the raw exception detail is
  logged for operator visibility.

`MediaService.process` is the only caller; it forwards the user's Telegram
ID into `upload_file` as the `user_id=` keyword argument so files always
land in the correct per-user subfolder. The handlers `handle_photo` and
`handle_document` (`bot/handlers/messages.py`) read `user_id` directly from
`message.from_user.id` and pass it to `MediaService.process`. Anonymous
messages (no `from_user`) are dropped before any Drive call so a missing id
is never silently coerced into a placeholder that would mix folders across
users.

---

## AI Integration

### Claude Client (`bot/services/claude_client.py`)

Single wrapper for all Claude API calls. Configured with `ANTHROPIC_API_KEY` and
the model from `Config`. Returns the text content of the first response block.

### Prompts in use

| Service | Prompt purpose | Output format |
|---------|---------------|---------------|
| `ClassifierService` | Classify text into task/idea/note | `{"type": "..."}` |
| `LinkService` | Summarize a web page | Plain text — line 1 = title, lines 3+ = prose body |
| `IdeaService._extract_tags` | Extract 1-5 keyword tags | `["tag1", "tag2"]` |
| `IdeaService._classify_complexity` | Estimate complexity and effort | `{"complexity": ..., "effort": ...}` |
| `IdeaService.suggest` | Suggest ideas from backlog | Free text (in the user's language) |
| `VisionService.analyze` | Categorize + describe an image | `{"category": ..., "description": ...}` |
| `TimeParser` | Parse natural-language time expressions | ISO timestamp or structured time |

All Claude prompts that return JSON also handle markdown code-fence stripping because
Claude sometimes wraps JSON in ` ```json ``` ` blocks.

### Prompt localization

Every user-facing Claude prompt carries the user's interface language so the
generated content (link summary, idea tags, suggestions, image descriptions) is
produced in the right language. The language code (`"ru"` / `"en"`) comes from
`UserSettings.language` and is resolved once per update by `DependencyMiddleware`
(injected as the `lang` handler argument). Handlers forward it into the service
call; services interpolate the human-readable name via
`bot.i18n.language_name(lang)` (e.g. `"Russian"`, `"English"`) into a
`{language}` placeholder in the prompt template. Unknown codes fall back to the
default language (English) so prompts never contain an empty placeholder.

Public service signatures that accept `lang` (keyword-only or default
`"en"`):

- `ClassifierService.classify(text, *, has_media, lang)`
- `LinkService.summarize(url, user_id, item_id, lang)`
- `IdeaService.save_idea(text, user_id, lang)` and `suggest(user_id, query, lang)`
- `VisionService.analyze(image_bytes, media_type, lang)`
- `MediaService.process(file_bytes, filename, user_id, media_type, lang)`

`NoteService` and `TaskService` do not call Claude and therefore don't take
`lang`. The hardcoded "Force Russian" instructions previously added in PR #100
have been replaced with the dynamic placeholder.

---

## Reminder Lifecycle

```
User sends task
      │
      ▼
task_service.save() → Item(type=task) created
      │
      ▼
has_time_expression(text)?
      ├── no  → "Задача сохранена!" + кнопка «⏰ Напомнить»
      │              │
      │         User presses «⏰ Напомнить»
      │              │
      │              ▼
      │         FSM waiting_for_time → user enters time
      │              │
      │              ▼
      └── yes → time_parser.parse() [Claude]
                    ├── success → reminder_service.create() → "🔔 Напомню <time>!"
                    └── parse fail → FSM waiting_for_time → user enters time manually
                                          │
                                          ▼
                                    time_parser.parse() → reminder_service.create()
      │
      ▼
[APScheduler, every 60s]
scheduler._send_due_reminders()
      │
      ▼
Bot sends: "🔔 Напоминание: <content>"
+ keyboard: [⏰ +1ч] [🌙 +1д] [✅ Принято]
      │
      ├── set auto_archive_at = now + 24h
      │
      ├── User presses ✅ Принято → reminder.is_acknowledged = True, auto_archive_at = None → done
      │
      ├── User presses ⏰ +1ч → original acknowledged + new Reminder in 1 hour (snooze_count++)
      │
      ├── User presses 🌙 +1д → original acknowledged + new Reminder in 1 day (snooze_count++)
      │
      └── No action for 24 hours:
              scheduler._auto_archive_reminders()  [also runs every 60s]
                    │
                    ▼
              reminder.is_auto_completed = True, auto_archive_at = None
              Bot sends: "✅ Задача автоматически помечена как выполненная: …"
              + keyboard: [🔄 Реактивировать]
                    │
                    └── User presses 🔄 Реактивировать (handler `cb_remind_reactivate`):
                          reset is_auto_completed/is_acknowledged/is_sent/is_cancelled to False
                          remind_at = now → bot sends the reminder again immediately
                          set auto_archive_at = now + 24h (the cycle can repeat)
```

---

## Timezone Setup

`bot/handlers/timezone_setup.py` implements a reusable three-step inline FSM for
capturing the user's timezone. It is launched from `/start` when no row exists in
`user_settings`, and is also the entry point used by `/config timezone`
(`bot/handlers/config.py`) — which always shows the picker, regardless of whether a
timezone is already stored, so the user can change it at any time.

The `/config` handler keeps settings declarative: each setting is an entry in a
module-level `_SETTINGS` tuple with a `key`, `label`, and `launch` callable.
Both the sub-command dispatcher (`/config <key>`) and the inline menu callback
read from the same registry, so adding a new setting (e.g. `/config language`)
means appending one entry — no branching logic to update.

Steps:

1. **Continent** — Europe / Asia / America / Other.
2. **Country** — curated list per continent, filtered at runtime against
   `zoneinfo.available_timezones()` so only zones shipped with the current tzdata are
   offered.
3. **Zone/City** — offered only if the selected country maps to more than one IANA zone;
   countries with a single zone (e.g. Germany → `Europe/Berlin`) skip this step.

Country dictionaries (`_EUROPE_COUNTRIES`, `_ASIA_COUNTRIES`, `_AMERICA_COUNTRIES`,
`_OTHER_COUNTRIES`) are keyed by ASCII slugs (`"russia"`, `"germany"`, …) — internal
identifiers that decouple the data from the UI. Localized country names live in a
separate `_COUNTRY_LABELS: dict[slug, dict[lang, name]]` table used by the
`_country_label(slug, lang)` helper, which renders the right language for the user
(issue #122). The slug — not the localized name — is what gets persisted into the FSM
state, so language changes and renames cannot break in-flight pickers. Callbacks key
off numeric indices, so adding/renaming countries does not require migrating any
stored callback data. New countries without a translation entry render as a
title-cased slug (`"new_country"` → `"New Country"`), keeping the picker usable until
labels are added.

On confirmation the handler calls `UserSettingsService.set_timezone()` which validates
the IANA name with `zoneinfo.ZoneInfo` before persisting. The confirmation message shows
the canonical IANA name and the current UTC offset (e.g. `Europe/Moscow (UTC+03:00)`).

`/start` differentiates "user hasn't set a timezone" from "user explicitly picked UTC"
using `UserSettingsService.has_timezone()`, which returns `True` only when a row exists
in `user_settings`.

### Timezone-aware time parsing

`TimeParser.parse(text, now, user_tz="UTC")` accepts the user's IANA timezone and
interprets free-form expressions (e.g. "завтра в 10") as **local** time in `user_tz`,
converting the result to UTC before returning. Handlers that create reminders
(`receive_reminder_time` in `handlers/reminders.py` and `_handle_task_with_time` in
`handlers/messages.py` / `handlers/voice.py`) fetch the timezone via
`UserSettingsService.get_timezone(user_id)` and pass it to the parser.

Return-type contract (backward-compatible):

- `user_tz == "UTC"` (default) — returns a **naive** UTC `datetime` (legacy behaviour).
- Any other zone — returns an **aware** UTC `datetime` (`tzinfo=timezone.utc`).

An invalid IANA name falls back silently to UTC and logs a warning.

### Timezone-aware datetime formatting for user-facing messages

`bot/utils/datetime_utils.py` exposes `format_remind_at(dt, user_tz)` which converts
a stored UTC `datetime` to the user's local timezone for display. The output is
`"DD.MM.YYYY HH:MM <ZONE>"`, where `<ZONE>` is the timezone abbreviation reported by
`zoneinfo` (e.g. `MSK`, `EDT`, `IST`) when it is alphabetic, or the IANA name
(e.g. `Asia/Kabul`) for zones whose `tzname()` returns a numeric offset string.

Naive datetimes are treated as UTC (legacy contract). Invalid IANA names fall back
silently to UTC.

Call sites:

- `cmd_reminders` (`/reminders` listing) — uses the user's stored timezone.
- `receive_reminder_time` (FSM confirmation when a reminder is created).
- `_handle_task_with_time` (auto-created reminder confirmation in
  `handlers/messages.py` / `handlers/voice.py`).
- `cb_remind_snooze` (snooze confirmation).
- `_send_due_reminders` and `_auto_archive_reminders` in `bot/scheduler.py` —
  the scheduler builds its own `UserSettingsService` per tick to look up the
  recipient's timezone, since the DI middleware does not run for background jobs.

---

## Access Control

`AuthMiddleware` (`bot/middlewares/auth.py`) runs on every update before any handler.

- If `ALLOWED_USER_IDS` is set in config: only those Telegram user IDs can interact with the bot.
  All other users are silently ignored (no response, no error). This is **allowlist mode** — it
  fails closed by default.
- If `ALLOWED_USER_IDS` is empty: any authenticated Telegram user may interact with the bot.
  This is **open mode** — no registration or invitation required.

In both modes, Telegram events with no `from_user` (e.g. anonymous channel posts) are silently
dropped before reaching any handler. Every handler requires a valid `user_id` to scope DB
operations to the correct user, so anonymous events can never reach user-owned data.

### First-use settings creation

When a user sends their first message the bot auto-creates a `UserSettings` row with sensible
defaults (timezone `UTC`, language derived from `from_user.language_code`). This happens in two
places:

- **`/start` handler** (`bot/handlers/commands.py`): calls
  `UserSettingsService.ensure_user_settings()` on the welcome-message path (i.e. when a timezone
  was already set or the service is not wired). For brand-new users the timezone FSM is launched
  instead; the settings row is created later when the user completes the FSM via `set_timezone`.
- **`handle_text` handler** (`bot/handlers/messages.py`): calls `ensure_user_settings()` at the
  top of every text message before any user-owned work begins, covering users who send their first
  message without running `/start` first.

`ensure_user_settings` is idempotent — if the row already exists it is returned unchanged.

### Per-user data isolation

All repository methods that operate on user-owned data are split into two
families:

- **User-scoped methods** — every read and every mutation triggered by a
  user-controlled ID (FSM state, callback payload, message text) goes through a
  method whose name ends with `_for_user` or that takes `user_id` as a required
  argument. The SQL filters on `user_id` (or joins to `items.user_id` for child
  rows like `Reminder` and `Idea`). Examples: `ItemRepository.get_by_id_for_user`,
  `ItemRepository.update_scraped_text_for_user`, `ItemRepository.search`,
  `IdeaRepository.search_by_embedding`, `ReminderRepository.get_by_id_for_user`,
  `ReminderRepository.get_upcoming`.
- **System-scoped methods** — used only by the background scheduler or by
  services immediately after they themselves created the row. These do not take
  `user_id`. Examples: `ItemRepository.update_embedding`,
  `ItemRepository.get_missing_embedding`, `ReminderRepository.get_due`,
  `ReminderRepository.get_due_auto_archive`,
  `ReminderRepository.mark_auto_completed`. They must never be called with a
  user-supplied ID.

  `ReminderRepository` also exposes mutation methods (`cancel`, `acknowledge`,
  `mark_auto_completed`, `reactivate`, `reset_auto_archive_at`) that operate by
  reminder ID without a `user_id` filter — these are **system-only** and are
  called exclusively by `ReminderService` after it has already verified
  ownership via `get_by_id_for_user`. Handlers never invoke these methods
  directly; they always go through the service-layer counterparts
  (`cancel_for_user`, `acknowledge`, `snooze`, `reset_auto_archive_at`,
  `reactivate_for_user`) which enforce the ownership check before delegating.

The split prevents callback handlers from being able to read or mutate another
user's data even when an attacker forges a valid-looking record ID. Integration
tests in `tests/integration/test_repository_user_isolation.py` create rows for
two distinct users and verify that the user-scoped queries and service-layer
mutations never return or modify the other user's rows.

---

## Background Scheduler

`bot/scheduler.py` runs APScheduler jobs in the background:

| Job | Interval | Function | What it does |
|-----|----------|----------|-------------|
| Due reminders | 60 seconds | `_send_due_reminders` | Finds reminders where `remind_at <= now`, not sent, not cancelled/acknowledged. Sends notification with snooze/ack keyboard. Sets `auto_archive_at = now + 24h`. |
| Auto-archive | 60 seconds | `_auto_archive_reminders` | Finds reminders where `auto_archive_at <= now` and none of the close flags are set. Marks them `is_auto_completed = True`, clears the timer, and sends a final message with a single `🔄 Реактивировать` button. There are no intermediate auto-resends — between the first delivery and the auto-archive close, the user is silent for a full 24h. |
| Reindex embeddings | 10 minutes | `_reindex_missing_embeddings` | Batches up to 50 Items and 50 Ideas with `embedding IS NULL`, calls `EmbeddingService`, and persists the resulting vectors. Sleeps 22 s after every successful embedding to stay under Voyage AI's free-tier rate limit. Skips the run when a user-triggered `/reindex` is already active. Failures per record are logged and skipped. Registered only when `start_scheduler()` is called with a `Config`. |

Each scheduler job opens its own DB session.

### Vector embeddings pipeline

`EmbeddingService` (`bot/services/embedding_service.py`) calls the Voyage AI Embeddings
API (`voyage-3.5`, 1024 dimensions) via `httpx`. When `VOYAGE_API_KEY` is not set, the
API is unreachable, or the response shape is unexpected, the service logs and returns
`None` — it never raises. On a `429 Too Many Requests` response the service retries the
request with exponential backoff (waits 2 s, then 8 s) before giving up and returning
`None`; other HTTP errors short-circuit immediately without retry.

At save time:

- `LinkService.save()` creates the `Item`, scrapes the page (best-effort), and
  generates the AI summary via Claude — all in one write before the first commit.
  Scraping failure is logged at WARNING; summary generation failure is also logged
  silently. In both cases the link is still persisted. After the commit the service
  attempts to generate and store the embedding. It returns a `SavedLink(item, indexed)`
  tuple; the handler shows `ℹ️ Умный поиск временно недоступен, запись сохранена без
  индексации.` when `indexed` is `False`. The `lang` argument forwards the user's
  interface language so the summary is generated in the correct language.
- `LinkService.summarize(url, user_id=..., item_id=...)` first checks whether the
  Item already has a stored `summary` — if so, it returns immediately without any
  Claude call or HTTP request. When no stored summary is available, it resolves the
  page text (from the `scraped_text` cache or via a fresh HTTP fetch) and calls
  Claude on demand. Fresh text is written back to the cache via
  `ItemRepository.update_scraped_text_for_user(item_id, user_id, ...)`, which silently
  no-ops for foreign-owned IDs. Only one `get_by_id_for_user` call is made per
  `summarize()` invocation regardless of the code path — the pre-fetched item is
  passed through to avoid a redundant DB round trip. Both the read
  (`get_by_id_for_user`) and the write are scoped by `user_id` so a
  callback-supplied ID for another user's Item never leaks or corrupts data.
- `IdeaService.save_idea()` persists the `Item` + `Idea`, commits, then attempts to
  generate embeddings for both records. The `SavedIdea.indexed` flag is `True` only
  when both vectors were produced and stored successfully; the handler shows the same
  notification otherwise.
- Records saved without an embedding (API outage, service disabled, partial failure)
  are eventually backfilled by the `_reindex_missing_embeddings` scheduler job.

### Semantic search

`SemanticSearchService` (`bot/services/semantic_search_service.py`) exposes a single
`search(user_id, query, limit=20, offset=0)` method that:

1. Generates an embedding for the query via `EmbeddingService.generate`.
   If the API is unavailable, raises `SemanticSearchUnavailableError`.
2. Calls `ItemRepository.search_by_embedding` and `IdeaRepository.search_by_embedding`
   — both use pgvector's cosine-distance operator (`<=>`) to return the nearest
   `limit + offset` rows per table, filtered by `user_id` and skipping rows where
   `embedding IS NULL`.
3. Merges the two result sets, sorts by score (higher = more similar, computed as
   `1 - cosine_distance`), and applies the requested pagination window.

Results are returned as a list of `SearchResult` dataclasses with fields
`id`, `type` (`"item"` or `"idea"`), `title`, `preview_text`, `score`, and
`created_at`. User isolation is enforced in the repository SQL — a user never
sees another user's records, even when sharing vector space.

### `/search` FSM

`bot/handlers/search.py` drives the user-facing search dialog:

1. `cmd_search` enters `SearchStates.choosing_mode` and shows two inline buttons:
   `🔍 Обычный` and `🧠 Умный (AI)`.
2. `cb_pick_mode` stores the choice in FSM data under `search_mode`
   (`"plain"` or `"smart"`) and transitions to `SearchStates.waiting_query`,
   prompting the user for a query.
3. `receive_search_query` runs `ListService.search` for plain mode or
   `SemanticSearchService.search` for smart mode. On success it transitions to
   `SearchStates.showing_results`, persists the query under `search_query` in
   FSM data, and renders the first page with `← Назад` / `Вперёд →` buttons.
4. `cb_search_page` re-runs the stored query for the requested page and edits
   the message in place.

Page size is fixed at 5 for both modes. Semantic results are rendered with a
`●●●●●` relevance bar derived from the cosine score (thresholds `0.9 / 0.75 /
0.6 / 0.45`). `SemanticSearchUnavailableError` and "service not injected" both
surface the same "Умный поиск временно недоступен. Попробуйте обычный поиск."
message without exiting the dialog, so the user can retry or `/cancel`.

### On-demand reindexing

`ReindexService` (`bot/services/reindex_service.py`) regenerates embeddings for
records that were saved while Voyage AI was unreachable. Unlike the background
`_reindex_missing_embeddings` scheduler job — which sweeps the global backlog
every ten minutes — `ReindexService` bulk runs are scoped to a single Telegram
user and are triggered from the `/reindex` command handler
(`bot/handlers/commands.py` → `cmd_reindex`).

`ReindexService` owns the shared in-memory lock for bulk reindexing. A
user-triggered `/reindex` reserves that user's ID; the scheduler reserves a
global scheduler slot. Only one bulk reindex source can own the slot at a time.
The scheduler skips its whole run while any user-triggered bulk run is active,
and `/reindex` replies with `ℹ️ Переиндексация уже выполняется, дождись
окончания.` while another command run or the scheduler already owns the slot.
Entries are cleared in `try/finally` blocks so failures do not leave a stale lock.
The handler also
calls `EmbeddingService.is_configured` first and replies `ℹ️ Умный поиск не
настроен в этом инстансе бота.` when Voyage AI is not wired in this deployment,
to distinguish that case from a transient outage.

- `count_unindexed_for_user(user_id) -> int` sums
  `ItemRepository.count_without_embedding` and
  `IdeaRepository.count_without_embedding` for the user. The `/reindex` handler
  uses it to short-circuit with `✅ Все твои записи уже проиндексированы.` when
  the backlog is empty, and to decide whether to append the `(будут обработаны
  первые 200)` suffix to the "starting run" message.

- `reindex_item(item_id, user_id) -> ReindexResult` and
  `reindex_idea(idea_id, user_id) -> ReindexResult` regenerate a single record.
  Both go through `*Repository.get_by_id_for_user` so a forged callback ID can
  never touch another user's data. They return one of:

  | `ReindexResult` | Meaning |
  |---|---|
  | `SUCCESS` | A vector was generated and persisted; the row's `embedding` is now non-NULL. |
  | `ALREADY_INDEXED` | The row already had an embedding — nothing was written. |
  | `NOT_FOUND` | No row with that id belongs to the requesting user. |
  | `SERVICE_UNAVAILABLE` | Voyage AI returned `None` (rate-limited, transport error, or key unset). Nothing was written. |

- `reindex_all_for_user(user_id, max_items=200) -> ReindexSummary` walks the
  user's Items (oldest first) and then their Ideas (oldest first), respecting a
  combined cap of `max_items` records per pass. A 100 ms pause is inserted
  between successive Voyage AI calls to stay below the provider's ~3 req/s
  ceiling. The result carries:

  | Field | Meaning |
  |---|---|
  | `succeeded` | Records whose embedding was generated and persisted. |
  | `failed` | Records where Voyage AI returned `None` after at least one earlier success in the same pass. |
  | `total_found` | How many unindexed records were loaded for this pass (≤ `max_items`). |
  | `truncated` | `True` when the user has more unindexed records than this pass loaded — call again to keep draining. |

  When the very first Voyage AI call of the pass returns `None`, the run is
  aborted immediately (the endpoint is assumed dead for this attempt) and the
  summary reports `succeeded = 0, failed = total_found` so the caller can tell
  the user "smart search is unavailable, try again later" without locking the
  backlog into a failed state.

- Repository surface: `ItemRepository.list_without_embedding(user_id, limit)` /
  `count_without_embedding(user_id)` and `IdeaRepository.list_without_embedding`
  / `count_without_embedding` / `get_by_id_for_user(idea_id, user_id)` — all
  scoped by `user_id`, oldest-first ordering for `list_*`. They are part of the
  user-scoped family described in the access-control section.

- Text fed into the embedding for a reindex matches what services produce at
  initial save: Items use `content + description + scraped_text` joined by blank
  lines, Ideas blend the parent Item's content with a `Теги: ...` line built
  from the idea's tags. The helpers live as `_build_item_text` /
  `_build_idea_text` static methods on `ReindexService`.

- Single-record retry from a chat notice goes through
  `bot/handlers/reindex.py`. When `LinkService` / `IdeaService` / `TaskService` /
  `NoteService` return `indexed=False`, the surrounding handler appends a
  `🔄 Попробовать ещё раз` inline button to the `embedding_unavailable_notice`
  message. The callback payload is `reindex:item:<uuid>` for Items and
  `reindex:idea:<uuid>` for Ideas — both well within Telegram's 64-byte limit.
  `handle_reindex_one` parses the payload, dispatches to
  `ReindexService.reindex_item` or `reindex_idea` (which scope by `user_id` via
  `*Repository.get_by_id_for_user`), and translates the `ReindexResult` into a
  user-visible outcome:

  | `ReindexResult` | UI effect |
  |---|---|
  | `SUCCESS` | Edits the notice to `reindex.one.success` and drops the keyboard. |
  | `ALREADY_INDEXED` | Alert `reindex.one.already_indexed` plus the same success edit. |
  | `SERVICE_UNAVAILABLE` | Edits the notice to `reindex.one.still_unavailable` and re-attaches the same `🔄 Попробовать ещё раз` button. |
  | `NOT_FOUND` | Alert `reindex.one.not_yours` — the chat message is **not** edited (protects against forged callback IDs). |

  When `edit_message_text` fails (Telegram refuses edits older than 48 h or with
  identical content), the handler falls back to `callback.message.answer()` so
  the user always sees the result.

---

## Configuration

All configuration is via environment variables (or `.env` file). Managed by
`pydantic-settings` in `bot/config.py`.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | — | Telegram Bot API token |
| `ANTHROPIC_API_KEY` | Yes | — | Claude API key |
| `DATABASE_URL` | No | `sqlite+aiosqlite:///data/bot.db` | SQLAlchemy async DB URL |
| `ALLOWED_USER_IDS` | No | `[]` (open) | Comma-separated Telegram user IDs. Non-empty → allowlist mode (only listed IDs allowed). Empty → open mode (any Telegram user allowed). In both modes all data is isolated per user. |
| `GROQ_API_KEY` | No | `""` | Groq API key (enables voice transcription) |
| `GOOGLE_DRIVE_CREDENTIALS_FILE` | No | `credentials.json` | Path (inside the container) to **OAuth 2.0 client secrets JSON** (downloaded from Google Cloud Console → "OAuth 2.0 Client IDs", Desktop app). Used once on first run to obtain user credentials via browser consent. The `prod` docker-compose profile mounts the host file of the same name (placed next to `docker-compose.yml`) read-only at `/app/credentials.json`. |
| `GOOGLE_DRIVE_TOKEN_FILE` | No | `token.json` | Path (inside the container) where the obtained user token (with refresh token) is persisted between runs. Auto-refreshed on subsequent runs. The `prod` docker-compose profile mounts the host file of the same name (placed next to `docker-compose.yml`) read-write at `/app/token.json` so the token survives container restarts and the Google OAuth library can rewrite it after a refresh. |
| `GOOGLE_DRIVE_FOLDER_ID` | No | `""` | Drive folder ID (enables media upload) |
| `VOYAGE_API_KEY` | No | `""` | Voyage AI API key (enables semantic search / embeddings) |
| `EMBEDDING_DIM` | No | `1024` | Dimensionality of embeddings produced by the embedding provider. Must match the `vector(N)` column size — changing it requires an Alembic migration. |
| `GHCR_USER` | Prod only | — | GitHub username used by Watchtower to authenticate against `ghcr.io` and pull the bot image. Required when running the `prod` profile in `docker-compose.yml`. |
| `GHCR_TOKEN` | Prod only | — | GitHub Personal Access Token with the `read:packages` scope. Used by Watchtower to pull `ghcr.io/krabbi/tg-smart-inbox:latest`. Required when running the `prod` profile. |

---

## Error Handling

All domain exceptions are defined in `bot/exceptions.py`:

| Exception | Raised when |
|-----------|-------------|
| `ClassificationError` | Claude API fails during message classification |
| `ScrapingError` | Web page fetch fails during link summarization |
| `DriveUploadError` | Google Drive upload fails |
| `TimeParseError` | Claude cannot parse a natural-language time expression |
| `TranscriptionError` | Groq Whisper transcription fails |
| `InvalidTimezoneError` | User-supplied timezone is not a valid IANA name |
| `InvalidLanguageError` | User-supplied language code is not in the supported set (`ru`, `en`) |
| `SemanticSearchUnavailableError` | Embedding API is unreachable, so semantic search cannot run |

Services raise these exceptions; handlers catch them and send user-friendly messages.
Raw exceptions never reach the user.

---

*For running locally, Docker deployment, CI/CD, and test commands — see [`docs/operations.md`](operations.md).*

