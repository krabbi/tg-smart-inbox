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
| `commands.py` | Bot commands: `/start`, `/list`, `/search`, `/reminders`, `/ideas`, `/help`, `/cancel` |
| `ideas.py` | `/ideas` command — display saved ideas |
| `voice.py` | Voice message transcription and routing |

### Services (`bot/services/`)

Services contain all business logic. They call repositories and external APIs. Services
own transaction boundaries — they call `session.commit()` after all repository calls succeed.

| File | Responsibility |
|------|---------------|
| `classifier.py` | Classify incoming messages: LINK / TASK / NOTE / IDEA / MEDIA |
| `claude_client.py` | Thin wrapper around the Anthropic API |
| `link_service.py` | Save links to DB, fetch page text and generate Claude summary |
| `reminder_service.py` | Create, cancel, snooze, acknowledge reminders |
| `time_parser.py` | Parse natural-language time expressions using Claude |
| `idea_service.py` | Save ideas with AI-extracted tags, complexity/effort, and suggestions |
| `task_service.py` | Save tasks to DB |
| `note_service.py` | Save notes to DB |
| `list_service.py` | Paginated item listing and full-text search |
| `media_service.py` | Process photos/files: vision categorization + Drive upload |
| `drive_service.py` | Google Drive API wrapper |
| `scraper.py` | HTTP page fetcher for link summarization |
| `transcription_service.py` | Groq Whisper API wrapper for voice messages |
| `vision_service.py` | Claude Vision API for image description |
| `user_settings_service.py` | Read/write per-user preferences (timezone) with IANA validation |

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

### `user_settings` table

Per-user preferences. One row per Telegram user; created lazily on first write.

| Column | Type | Description |
|--------|------|-------------|
| `user_id` | BigInteger (PK) | Telegram user ID |
| `timezone` | String(64) | IANA tz name (e.g. `Europe/Moscow`); NOT NULL, default `UTC` |
| `created_at` | DateTime (TZ) | Row creation timestamp |
| `updated_at` | DateTime (TZ) | Last update timestamp (auto-bumped on UPDATE) |

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
  ├── creates: ClaudeClient, ItemRepository, ReminderRepository, IdeaRepository
  ├── injects: classifier, link_service, reminder_service, time_parser,
  │            idea_service, task_service, note_service, list_service
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
                    └── snooze_count >= 5: silently acknowledge (stop spam)
```

---

## Access Control

`AuthMiddleware` (`bot/middlewares/auth.py`) runs on every update before any handler.

- If `ALLOWED_USER_IDS` is set in config: only those Telegram user IDs can interact with the bot.
  All other users are silently ignored (no response, no error).
- If `ALLOWED_USER_IDS` is empty: all users are allowed (open access).

This is a whitelist, not a blocklist — it fails closed by default.

---

## Background Scheduler

`bot/scheduler.py` runs two APScheduler jobs every 60 seconds:

| Job | Function | What it does |
|-----|----------|-------------|
| Due reminders | `_send_due_reminders` | Finds reminders where `remind_at <= now`, not sent, not cancelled/acknowledged. Sends notification with snooze/ack keyboard. Sets `auto_resend_at = now + 5min`. |
| Auto-resend | `_auto_resend_reminders` | Finds reminders where `auto_resend_at <= now`. If `snooze_count < 5`, creates new reminder and re-notifies. If `>= 5`, silently acknowledges. |

Each scheduler job opens its own DB session.

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
│   │   ├── commands.py       # /start /list /search /reminders /ideas /cancel
│   │   ├── ideas.py          # /ideas command
│   │   └── voice.py          # Voice message handling
│   ├── services/
│   │   ├── classifier.py     # Message type classification
│   │   ├── claude_client.py  # Anthropic API wrapper
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
