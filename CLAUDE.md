# CLAUDE.md — Project Guide

This file is always loaded. It covers what every agent needs to know upfront.
Detailed coding patterns and testing conventions are in `.claude/` — load them when you need them.

---

## Project overview

`tg-smart-inbox` is a Telegram bot that classifies and processes forwarded messages:
summarizes links, creates reminders for tasks, uploads media to Google Drive, stores ideas,
and transcribes voice messages.

**Stack:** Python 3.11+, aiogram 3.x, SQLAlchemy async + Alembic, Claude API (Anthropic),
APScheduler, Groq Whisper API (optional), Google Drive API (optional).

**Full technical reference:** [`docs/architecture.md`](docs/architecture.md)
**User-facing reference:** [`docs/user_guide.md`](docs/user_guide.md)

---

## Architecture

Three strict layers — never skip or cross them:

```
Handler (aiogram)  →  Service (business logic)  →  Repository (DB access)
```

- **Handlers** — thin: call services, reply to user. No logic, no DB, no external APIs.
- **Services** — all business logic. Own transaction boundaries (`commit()`). No Telegram calls.
- **Repositories** — only layer with `AsyncSession`. Use `flush()`, never `commit()`.

For code examples and patterns → **read `.claude/coding-patterns.md`**.

---

## Agent workflow

Three specialized subagents. Use them in this order for every non-trivial feature.

| Agent | Role |
|---|---|
| `product-manager` | Requirements, edge cases, GitHub issue creation, product acceptance review |
| `coder` | End-to-end implementation: code + tests + docs, drives PR to merge |
| `pr-reviewer` | Code review: architecture, tests, security, linting, docs coverage |

### Standard flow

```
1. product-manager  →  clarifies requirements, creates GitHub issues
2. coder            →  implements (code + tests + docs), creates PR
3. pr-reviewer      →  code review; CHANGES_REQUESTED → coder fixes → re-review
4. product-manager  →  product acceptance review (ONLY if docs/user_guide.md changed)
                        PRODUCT CHANGES REQUESTED → coder fixes → back to step 3
5. gh pr merge --squash --delete-branch
```

### Merge gates

- Every PR needs `pr-reviewer` **APPROVED** before merge.
- PRs that change `docs/user_guide.md` also need `product-manager` **PRODUCT APPROVED**.

### Product questions during implementation

- **Significant** (UX, data model, scope) → consult `product-manager` agent.
- **Minor** (naming, log level, internal detail) → decide and note in a comment.

---

## Code style

| Tool | Config |
|---|---|
| Formatter | `ruff format` (line length 100) |
| Linter | `ruff check` rules: E, F, I, UP, B, SIM |
| Type hints | Required on all function signatures |
| Python version | 3.11+ (`X \| Y`, `match`, etc.) |

```bash
make format    # ruff format .
make lint      # ruff check .
make coverage  # pytest --cov; fails if coverage < 80%
```

All three must pass before pushing. CI rejects PRs that fail any of these.

---

## Language policy

All artifacts (issues, PR descriptions, code comments, docstrings, git commits) — **English**.
Respond to the operator in the language they write in.

---

## Commit convention

Follow [Conventional Commits](https://www.conventionalcommits.org/). Reference the issue number.

| Prefix | When |
|--------|------|
| `feat:` | New feature or user-visible behaviour |
| `fix:` | Bug fix |
| `refactor:` | No behaviour change |
| `test:` | Tests only |
| `docs:` | Documentation only |
| `chore:` | Tooling, config, dependencies |

Example: `feat: add snooze for reminders (#39)`

---

## Documentation — update rules

When your change affects any of the following, update the corresponding file **in the same PR**:

| What changed | File to update |
|---|---|
| New/changed user-facing command, button, or flow | `docs/user_guide.md` |
| New service, repository, model, config variable, DB schema | `docs/architecture.md` |
| New handler or service file | `docs/architecture.md` + file layout in `CLAUDE.md` |
| New Alembic migration | `docs/architecture.md` (DB schema section) |
| New env variable | `README.md` + `docs/architecture.md` |
| Coding convention or DI wiring change | `.claude/coding-patterns.md` + `CLAUDE.md` |
| Testing convention change | `.claude/testing-guide.md` |

---

## Detail files — load when needed

| File | When to read |
|---|---|
| `.claude/coding-patterns.md` | Before writing any handler, service, repository, or model |
| `.claude/testing-guide.md` | Before writing tests |
| `docs/architecture.md` | For DB schema, DI wiring, scheduler, config reference |
| `docs/user_guide.md` | For user-facing behaviour, commands, flows |

---

## File layout

```
bot/
  __main__.py           # entry point
  bot.py                # Bot + Dispatcher factories
  config.py             # pydantic-settings Config
  db.py                 # async engine + session factory
  exceptions.py         # all domain exceptions
  i18n.py               # interface string localization (ru/en) + t() helper
  middleware.py         # DependencyMiddleware — DI wiring
  scheduler.py          # APScheduler: due reminders + auto-resend + embedding reindex
  handlers/
    messages.py         # main router: text, photo, document
    links.py            # link action callbacks
    reminders.py        # reminder FSM + snooze/ack callbacks
    commands.py         # /start /help /list /reminders /ideas /reindex /cancel
    config.py           # /config settings menu (extensible sub-commands)
    ideas.py            # /ideas command
    search.py           # /search FSM — mode picker (plain/semantic) + pagination
    timezone_setup.py   # three-step FSM: continent → country → city
    reindex.py          # single-record reindex retry button + callback
    voice.py            # voice transcription + routing
  services/
    classifier.py       # LINK/TASK/NOTE/IDEA/MEDIA classification
    claude_client.py    # Anthropic API wrapper
    embedding_service.py # vector embeddings + graceful fallback
    link_service.py     # link save + summarization
    reminder_service.py
    time_parser.py      # natural-language time parsing
    idea_service.py     # idea save + suggestions
    task_service.py
    note_service.py
    list_service.py     # paginated listing + full-text search
    semantic_search_service.py # cosine-similarity search over Item and Idea embeddings
    reindex_service.py  # per-user single/bulk regeneration of missing embeddings
    media_service.py    # photo/file processing
    drive_service.py    # Google Drive upload
    scraper.py          # HTTP page fetcher
    transcription_service.py
    vision_service.py
    user_settings_service.py
  repositories/
    item_repository.py
    reminder_repository.py
    idea_repository.py
    user_settings.py
  models/
    base.py             # UUIDMixin, TimestampMixin
    item.py             # Item + ItemType
    reminder.py         # Reminder
    idea.py             # Idea + enums
    user_settings.py    # UserSettings (per-user prefs)
  middlewares/
    auth.py             # ALLOWED_USER_IDS whitelist
  utils/
    datetime_utils.py   # format_remind_at() — UTC → user tz formatting
    text.py             # extract_url() and helpers
alembic/                # migrations
web/
  __init__.py           # empty package marker
  main.py               # create_app() factory — CORS, lifespan, route registration
  auth.py               # verify_telegram_login, create_jwt, decode_jwt, verify_jwt_token
  dependencies.py       # get_db_session, get_current_user FastAPI deps
  routers/
    __init__.py         # empty package marker
    auth.py             # POST /api/auth/telegram, GET /api/auth/me
tests/
  conftest.py           # fake_config, db_session fixtures
  unit/
  integration/
docs/
  architecture.md
  user_guide.md
  operations.md           # running locally, Docker, CI/CD
.claude/
  agents/               # subagent definitions
  coding-patterns.md    # handler/service/repo code examples
  testing-guide.md      # test patterns and conventions
```
