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
| `reminders.py` | Reminder dialog (time input FSM), snooze/acknowledge callbacks |
| `commands.py` | Bot commands: `/start`, `/list`, `/reminders`, `/ideas`, `/help`, `/cancel` |
| `config.py` | `/config` command — extensible settings menu; currently dispatches to the timezone FSM |
| `ideas.py` | `/ideas` command — display saved ideas |
| `search.py` | `/search` command — FSM for picking search mode (plain / semantic) + paginated results |
| `voice.py` | Voice message transcription and routing |
| `timezone_setup.py` | Three-step inline FSM for picking a timezone (continent → country → city) |

### Services (`bot/services/`)

Services contain all business logic. They call repositories and external APIs. Services
own transaction boundaries — they call `session.commit()` after all repository calls succeed.

| File | Responsibility |
|------|---------------|
| `classifier.py` | Classify incoming messages: LINK / TASK / NOTE / IDEA / MEDIA |
| `claude_client.py` | Thin wrapper around the Anthropic API |
| `embedding_service.py` | Generate vector embeddings for Items and Ideas; gracefully returns `None` on API error |
| `link_service.py` | Save links to DB (with cached page text), reuse the cache when generating Claude summaries |
| `reminder_service.py` | Create, cancel, snooze, acknowledge reminders |
| `time_parser.py` | Parse natural-language time expressions using Claude (timezone-aware) |
| `idea_service.py` | Save ideas with AI-extracted tags, complexity/effort, and suggestions |
| `task_service.py` | Save tasks to DB |
| `note_service.py` | Save notes to DB |
| `list_service.py` | Paginated item listing and full-text search |
| `semantic_search_service.py` | Cosine-similarity search over Item and Idea embeddings via pgvector |
| `media_service.py` | Process photos/files: vision categorization + Drive upload |
| `drive_service.py` | Google Drive API wrapper |
| `scraper.py` | HTTP page fetcher for link summarization |
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
| `reminder_repository.py` | CRUD for `Reminder` records, due/auto-resend queries |
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
| `scraped_text` | Text (nullable) | Cached full page text for links (used to re-embed without re-scraping) |
| `embedding` | `vector(1536)` (nullable) | pgvector embedding for semantic search; ivfflat/cosine index |

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
| `snooze_count` | Integer | How many times this reminder was snoozed/auto-resent |
| `auto_resend_at` | DateTime (nullable) | When to auto-resend if not acknowledged |

### `ideas` table

Additional metadata for items with `type = idea`.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID (PK) | Auto-generated UUID |
| `item_id` | UUID (FK → items, unique) | The parent item |
| `tags` | JSON (list of str) | AI-extracted tags (max 5, max 30 chars each) |
| `complexity` | Enum (nullable) | `simple`, `medium`, `complex` |
| `effort` | Enum (nullable) | `quick` (<1h), `halfday` (1-4h), `day` (4-8h), `longterm` |
| `embedding` | `vector(1536)` (nullable) | pgvector embedding for idea-level semantic search; ivfflat/cosine index |

### pgvector extension

Semantic search uses the [pgvector](https://github.com/pgvector/pgvector) PostgreSQL
extension. The migration that introduces the `embedding` columns
(`98444ad48da7_add_pgvector_embeddings_and_scraped_text.py`) runs
`CREATE EXTENSION IF NOT EXISTS vector` on PostgreSQL, creates `embedding` columns of
type `vector(1536)` on both `items` and `ideas`, and builds `ivfflat` indexes with
`vector_cosine_ops` (100 lists) on each.

On SQLite (used only in tests) the migration and ORM still create the columns, but
the extension and the vector index are skipped because pgvector is PostgreSQL-only.
The dimensionality is exposed via the `EMBEDDING_DIM` config field (default `1536`,
matching OpenAI `text-embedding-3-small`); changing it requires a new Alembic
migration since vector columns have a fixed size.

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
  │            list_service, semantic_search_service, user_settings_service
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
| `IdeaService.suggest` | Suggest ideas from backlog | Free text (language matches query) |
| `TimeParser` | Parse natural-language time expressions | ISO timestamp or structured time |

All Claude prompts that return JSON also handle markdown code-fence stripping because
Claude sometimes wraps JSON in ` ```json ``` ` blocks.

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
      ├── set auto_resend_at = now + 5 minutes
      │
      ├── User presses ✅ Принято → reminder.is_acknowledged = True → done
      │
      ├── User presses ⏰ +1ч → new Reminder in 1 hour (snooze_count++)
      │
      ├── User presses 🌙 +1д → new Reminder in 1 day (snooze_count++)
      │
      └── No action for 5 minutes:
              scheduler._auto_resend_reminders()
                    │
                    ├── snooze_count < 5: auto-resend, snooze_count++
                    └── snooze_count >= 5: notify user ("🔔 Напоминание закрыто автоматически: …"), then acknowledge
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
- `_send_due_reminders` and `_auto_resend_reminders` in `bot/scheduler.py` —
  the scheduler builds its own `UserSettingsService` per tick to look up the
  recipient's timezone, since the DI middleware does not run for background jobs.

---

## Access Control

`AuthMiddleware` (`bot/middlewares/auth.py`) runs on every update before any handler.

- If `ALLOWED_USER_IDS` is set in config: only those Telegram user IDs can interact with the bot.
  All other users are silently ignored (no response, no error).
- If `ALLOWED_USER_IDS` is empty: all users are allowed (open access).

This is a whitelist, not a blocklist — it fails closed by default.

---

## Background Scheduler

`bot/scheduler.py` runs APScheduler jobs in the background:

| Job | Interval | Function | What it does |
|-----|----------|----------|-------------|
| Due reminders | 60 seconds | `_send_due_reminders` | Finds reminders where `remind_at <= now`, not sent, not cancelled/acknowledged. Sends notification with snooze/ack keyboard. Sets `auto_resend_at = now + 5min`. |
| Auto-resend | 60 seconds | `_auto_resend_reminders` | Finds reminders where `auto_resend_at <= now`. If `snooze_count < 5`, creates new reminder and re-notifies. If `>= 5`, silently acknowledges. |
| Reindex embeddings | 10 minutes + at startup | `_reindex_missing_embeddings` | Batches up to 50 Items and 50 Ideas with `embedding IS NULL`, calls `EmbeddingService`, and persists the resulting vectors. Failures per record are logged and skipped. Registered only when `start_scheduler()` is called with a `Config`. |

Each scheduler job opens its own DB session.

### Vector embeddings pipeline

`EmbeddingService` (`bot/services/embedding_service.py`) calls the Anthropic Embeddings
API via the SDK's low-level HTTP client. When the API is unreachable, returns a payload
with an unexpected shape, or produces a vector whose length does not match
`Config.embedding_dim`, the service logs and returns `None` — it never raises.

At save time:

- `LinkService.save()` creates the `Item`, calls `Scraper.fetch_text()` once and stores
  the result in `Item.scraped_text` before the first commit (best-effort: a scraper
  failure is logged at WARNING and the link is still persisted). After the commit,
  the service attempts to generate and store the embedding. It returns a
  `SavedLink(item, indexed)` tuple; the handler shows
  `ℹ️ Умный поиск временно недоступен, запись сохранена без индексации.` when
  `indexed` is `False`.
- `LinkService.summarize(url, item_id=...)` reuses the cached `scraped_text` when the
  Item has one — no HTTP request is made. On a cache miss the scraper is called and
  the fresh text is written back to the Item via `ItemRepository.update_scraped_text()`,
  so the next summary is served from cache.
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

---

## Configuration

All configuration is via environment variables (or `.env` file). Managed by
`pydantic-settings` in `bot/config.py`.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | — | Telegram Bot API token |
| `ANTHROPIC_API_KEY` | Yes | — | Claude API key |
| `DATABASE_URL` | No | `sqlite+aiosqlite:///data/bot.db` | SQLAlchemy async DB URL |
| `ALLOWED_USER_IDS` | No | `[]` (open) | Comma-separated Telegram user IDs |
| `GROQ_API_KEY` | No | `""` | Groq API key (enables voice transcription) |
| `GOOGLE_DRIVE_CREDENTIALS_FILE` | No | `credentials.json` | Path to Drive service account JSON |
| `GOOGLE_DRIVE_FOLDER_ID` | No | `""` | Drive folder ID (enables media upload) |
| `EMBEDDING_DIM` | No | `1536` | Dimensionality of embeddings produced by the embedding provider. Must match the `vector(N)` column size — changing it requires an Alembic migration. |

---

## Running Locally

```bash
# Install dev dependencies
make install

# Copy and fill in .env
cp .env.example .env

# Apply DB migrations
alembic upgrade head

# Run the bot
make run
```

## Running with Docker

```bash
# Production (PostgreSQL + bot)
POSTGRES_PASSWORD=secret docker compose --profile prod up -d

# Development (hot-reload, source mounted)
POSTGRES_PASSWORD=secret docker compose --profile dev up
```

The dev profile mounts `./bot` as a volume and uses `watchfiles` to restart on
any Python file change.

---

## Testing

```bash
make test        # run all tests
make coverage    # run with coverage report (fails if < 80%)
make lint        # ruff check
make format      # ruff format
```

Test layout mirrors source layout:
```
bot/services/link_service.py  →  tests/unit/test_link_service.py
bot/repositories/item_*.py   →  tests/unit/test_item_repository.py
                              →  tests/integration/test_idea_repository.py
```

- **Unit tests** (`tests/unit/`) — mock all external dependencies (DB session, Claude, Drive).
- **Integration tests** (`tests/integration/`) — test the Service → Repository chain against
  in-memory SQLite (`db_session` fixture from `tests/conftest.py`).

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

## File Layout Reference

```
tg-smart-inbox/
├── bot/
│   ├── __main__.py           # Entry point — wires deps, starts polling
│   ├── bot.py                # Bot + Dispatcher factories
│   ├── config.py             # pydantic-settings Config
│   ├── db.py                 # Async engine + session factory
│   ├── exceptions.py         # All domain exceptions
│   ├── middleware.py         # DependencyMiddleware — DI wiring
│   ├── scheduler.py          # APScheduler jobs for reminders
│   ├── handlers/
│   │   ├── messages.py       # Main text/photo/document router
│   │   ├── links.py          # Link action callbacks
│   │   ├── reminders.py      # Reminder FSM and snooze/ack callbacks
│   │   ├── commands.py       # /start /list /reminders /ideas /cancel
│   │   ├── config.py         # /config settings menu (extensible sub-commands)
│   │   ├── ideas.py          # /ideas command
│   │   ├── search.py         # /search FSM — mode picker (plain/semantic) + pagination
│   │   ├── timezone_setup.py # Three-step FSM for picking a timezone
│   │   └── voice.py          # Voice message handling
│   ├── services/
│   │   ├── classifier.py     # Message type classification
│   │   ├── claude_client.py  # Anthropic API wrapper
│   │   ├── embedding_service.py  # Vector embeddings via Anthropic Embeddings API
│   │   ├── link_service.py   # Link save + summarize
│   │   ├── reminder_service.py # Reminder business logic
│   │   ├── time_parser.py    # Natural-language time parsing
│   │   ├── idea_service.py   # Idea save + suggest
│   │   ├── task_service.py   # Task save
│   │   ├── note_service.py   # Note save
│   │   ├── list_service.py   # Listing + search
│   │   ├── media_service.py  # Photo/file processing
│   │   ├── drive_service.py  # Google Drive upload
│   │   ├── scraper.py        # HTTP page fetcher
│   │   ├── transcription_service.py  # Groq Whisper
│   │   ├── vision_service.py # Claude Vision
│   │   └── user_settings_service.py  # Per-user preferences (timezone)
│   ├── repositories/
│   │   ├── item_repository.py
│   │   ├── reminder_repository.py
│   │   ├── idea_repository.py
│   │   └── user_settings.py
│   ├── models/
│   │   ├── base.py           # UUIDMixin, TimestampMixin
│   │   ├── item.py           # Item + ItemType
│   │   ├── reminder.py       # Reminder
│   │   ├── idea.py           # Idea + IdeaComplexity + IdeaEffort
│   │   └── user_settings.py  # UserSettings (per-user prefs)
│   ├── middlewares/
│   │   └── auth.py           # AuthMiddleware — user ID whitelist
│   └── utils/
│       ├── datetime_utils.py # format_remind_at() — UTC → user tz formatting
│       └── text.py           # extract_url() and other text helpers
├── alembic/                  # DB migrations
├── tests/
│   ├── conftest.py           # Shared fixtures: fake_config, db_session
│   ├── unit/                 # Fast mocked tests
│   └── integration/          # Service+Repository tests with SQLite
├── docs/
│   ├── architecture.md       # This file
│   └── user_guide.md         # User-facing documentation
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── pyproject.toml
└── CLAUDE.md                 # Coding guidelines for AI assistants
```
