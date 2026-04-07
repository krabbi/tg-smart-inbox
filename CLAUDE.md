# CLAUDE.md — Architecture & Coding Guidelines

This file is the authoritative guide for all code written in this repository. Read it before writing any code. Every decision here was made intentionally — follow it consistently.

---

## Project overview

`tg-smart-inbox` is a Telegram bot that classifies and processes forwarded messages: summarizes links, creates reminders for tasks, uploads media to Google Drive, stores ideas, and transcribes voice messages.

**Stack:** Python 3.11+, aiogram 3.x, SQLAlchemy async + Alembic, Claude API (Anthropic), Google Drive API, APScheduler, Groq Whisper API.

For a full technical description see [`docs/architecture.md`](docs/architecture.md).

---

## Architecture: 3-layer pattern

```
Handler (aiogram)  →  Service (business logic)  →  Repository (DB access)
```

### Handlers (`bot/handlers/`)
- Thin layer: validate input, call one or more services, send a Telegram response.
- No business logic. No direct DB access. No external API calls.
- One handler file per feature domain (e.g. `links.py`, `reminders.py`).

```python
# Good
async def handle_link(message: Message, link_service: LinkService) -> None:
    """Handle incoming link message."""
    try:
        result = await link_service.process(message.text, message.from_user.id)
        await message.answer(result.reply_text, reply_markup=result.keyboard)
    except LinkProcessingError:
        await message.answer("Не удалось обработать ссылку. Попробуй ещё раз.")

# Bad — business logic in handler
async def handle_link(message: Message, session: AsyncSession) -> None:
    item = Item(user_id=message.from_user.id, type=ItemType.link, content=message.text)
    session.add(item)
    await session.commit()
```

### Services (`bot/services/`)
- All business logic lives here.
- No direct SQLAlchemy session usage — call repositories instead.
- No Telegram API calls (no `message.answer()` etc).
- External APIs (Claude, Google Drive, Groq) are wrapped in dedicated service classes (`claude_client.py`, `drive_service.py`, `transcription_service.py`).
- Services return result dataclasses defined alongside them (see Result objects below).

```python
# Good
class LinkService:
    """Processes incoming links: saves to DB and prepares user response."""

    def __init__(self, item_repo: ItemRepository, claude: ClaudeClient) -> None:
        self._repo = item_repo
        self._claude = claude

    async def process(self, url: str, user_id: int) -> LinkResult:
        """Save link and return action keyboard for user."""
        item = await self._repo.create(user_id=user_id, type=ItemType.link, content=url)
        return LinkResult(item_id=item.id, reply_text="Сохранено!", keyboard=build_link_keyboard(item.id))
```

### Repositories (`bot/repositories/`)
- The only layer that holds an `AsyncSession` and runs SQLAlchemy queries.
- No business logic. Only CRUD and query operations.
- One repository class per model (e.g. `ItemRepository`, `ReminderRepository`).
- Use `flush()` + `refresh()` inside repositories, not `commit()`. Transaction boundaries are owned by the **service layer** (or middleware). This allows services to batch multiple repository calls into one atomic transaction.

```python
# Good
class ItemRepository:
    """CRUD access for Item records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, user_id: int, type: ItemType, content: str) -> Item:
        """Create and flush a new Item; caller is responsible for commit."""
        item = Item(user_id=user_id, type=type, content=content)
        self._session.add(item)
        await self._session.flush()
        await self._session.refresh(item)
        return item
```

Services commit after all repository calls succeed:

```python
async def process(self, url: str, user_id: int) -> LinkResult:
    """Save link atomically."""
    item = await self._repo.create(user_id=user_id, type=ItemType.link, content=url)
    await self._session.commit()   # service owns the transaction boundary
    return LinkResult(...)
```

---

## Result objects

Services return simple frozen dataclasses, defined in the same file as the service:

```python
from dataclasses import dataclass
import uuid
from aiogram.types import InlineKeyboardMarkup

@dataclass(frozen=True)
class LinkResult:
    item_id: uuid.UUID
    reply_text: str
    keyboard: InlineKeyboardMarkup
```

---

## Dependency injection

Dependencies are wired per-request in `bot/middleware.py` (`DependencyMiddleware`) and injected into handlers via aiogram's `data` dict.

On every update the middleware:
1. Opens an `AsyncSession`
2. Instantiates all repositories and services
3. Injects them into `data`
4. For **optional** services (voice, media) injects `None` when the required credentials are absent

```python
# bot/middleware.py — simplified
async def __call__(self, handler, event, data):
    async with self._factory() as session:
        claude = ClaudeClient(self._config)
        item_repo = ItemRepository(session)
        data["link_service"] = LinkService(session=session, item_repo=item_repo, ...)
        data["reminder_service"] = ReminderService(session=session, repo=ReminderRepository(session))

        # Optional — injected as None when credentials are missing
        if self._config.groq_api_key:
            data["transcription_service"] = TranscriptionService(self._config)
        else:
            data["transcription_service"] = None

        return await handler(event, data)
```

Handlers declare injected services as keyword arguments — aiogram resolves them from `data`.
Optional services must be declared with `| None` and checked before use:

```python
async def handle_voice(message: Message, transcription_service: TranscriptionService | None = None) -> None:
    if transcription_service is None:
        await message.answer("Голосовые сообщения не настроены.")
        return
    ...
```

---

## Error handling

- Define all domain exceptions in `bot/exceptions.py`. Import from there in both services and handlers.
- Services raise specific domain exceptions: `ClassificationError`, `DriveUploadError`, `ScrapingError`, `TimeParseError`, `TranscriptionError`, etc.
- Handlers catch domain exceptions and send user-friendly Telegram messages.
- Raw exceptions must never reach the user.
- Log errors with context at the service level before re-raising.

```python
# bot/exceptions.py
class ClassificationError(Exception):
    """Raised when Claude API fails to classify a message."""

class DriveUploadError(Exception):
    """Raised when Google Drive upload fails."""

class ScrapingError(Exception):
    """Raised when a URL cannot be fetched or parsed."""

class TimeParseError(Exception):
    """Raised when a natural language time expression cannot be parsed."""

class TranscriptionError(Exception):
    """Raised when Whisper API fails to transcribe audio."""
```

```python
# Handler catches:
try:
    result = await classifier.classify(text)
except ClassificationError:
    await message.answer("Не удалось обработать сообщение. Попробуй ещё раз.")
    return
```

---

## Testing conventions

### Structure
Test file mirrors source file:
```
bot/services/classifier.py   →  tests/unit/test_classifier.py
bot/repositories/item.py     →  tests/unit/test_item_repository.py
```

### Unit tests (`tests/unit/`)
- Mock all external dependencies: Claude API, Google Drive API, DB sessions.
- Use `pytest-mock` (`mocker` fixture).
- Fast — no I/O, no network.

### Integration tests (`tests/integration/`)
- Test the **Service → Repository** chain against an in-memory SQLite `db_session` fixture.
- External APIs (Claude, Drive) are still mocked.
- Handler-level integration (full update pipeline) requires aiogram's `process_update` / `InMemoryStorage` — out of scope for most tests in this project.

### Rules
- Use `pytest-asyncio` for all async tests. `asyncio_mode = "auto"` is set in `pyproject.toml`.
- Use `fake_config` and `db_session` fixtures from `tests/conftest.py`.
- Target: **≥ 80% coverage** on all new code. Run with `make coverage` (runs pytest with `--cov`).
- `make test` runs pytest without coverage; use it for quick iteration. CI gate uses `make coverage`.
- Never use real API keys, tokens, or production DB in tests.

---

## Documentation

When you change behaviour that is described in the docs, update the docs too:

| What changed | File to update |
|---|---|
| Architecture, services, DB schema, DI, config | `docs/architecture.md` |
| User-visible commands, flows, bot responses | `docs/user_guide.md` |
| Coding conventions, tooling, contribution process | `CLAUDE.md`, `CONTRIBUTING.md` |
| Project overview, setup instructions | `README.md` |

---

## Comments policy

- Write comments only where the logic is **non-obvious** (e.g. a workaround, a tricky algorithm, or an API quirk).
- Prefer self-documenting names over explanatory comments.
- Every public function and class must have a one-line docstring (imperative mood, Google style).

```python
# Good
async def get_pending_reminders(self, now: datetime) -> list[Reminder]:
    """Return all unsent, non-cancelled reminders due before `now`."""
    ...

# Bad — comment restates the code
# Commit the session
await session.commit()
```

---

## Commit convention

Follow [Conventional Commits](https://www.conventionalcommits.org/):

| Prefix | When to use |
|--------|-------------|
| `feat:` | New feature or user-visible behaviour |
| `fix:` | Bug fix |
| `refactor:` | Code change with no behaviour change |
| `test:` | Adding or updating tests |
| `docs:` | Documentation only |
| `chore:` | Tooling, config, dependencies |

Rules:
- One logical change per commit.
- Imperative mood in subject line: "add reminder flow" not "added reminder flow".
- Reference the issue: `feat: AI classifier (#5)`.

---

## Code style

| Tool | Config |
|------|--------|
| Formatter | `ruff format` (line length 100) |
| Linter | `ruff check` rules: E, F, I, UP, B, SIM |
| Type hints | Required on all function signatures |
| Python version | 3.11+ — use modern syntax (`X \| Y`, `match`, etc.) |

Run before every commit:
```bash
make lint      # ruff check .
make format    # ruff format .
make coverage  # pytest with --cov; fails if coverage < 80%
```

All three must pass. CI will reject PRs that fail any of these.

---

## Agent workflow

The project uses three specialized subagents. Use them in this order for any non-trivial work.

### Agents

| Agent | Role | When to invoke |
|---|---|---|
| `product-manager` | Requirements, edge cases, GitHub issue creation, product acceptance review | Before implementing any non-trivial feature; when product questions arise during implementation |
| `coder` | End-to-end implementation: code + tests + docs, drives PR to merge | After requirements are clear and issues are created |
| `pr-reviewer` | Code review: architecture, tests, security, linting, docs coverage | After every PR is created, before merge |

### Standard feature flow

```
1. product-manager
   └── Interviews user → clarifies requirements → explores edge cases
   └── Creates GitHub issues (parent + subtasks)

2. coder
   └── Reads issue → studies code → implements (code + tests + docs)
   └── Runs: make format && make lint && make coverage
   └── Creates PR → requests pr-reviewer

3. pr-reviewer
   └── APPROVED → continue
   └── CHANGES_REQUESTED → coder fixes → pr-reviewer again

4. (only if docs/user_guide.md changed)
   product-manager product acceptance review
   └── PRODUCT APPROVED → merge
   └── PRODUCT CHANGES REQUESTED → coder fixes → pr-reviewer → product-manager again

5. gh pr merge --squash --delete-branch
```

### Product questions during implementation

If **coder** hits a product question (edge case behaviour, error message copy, scope boundary):
- **Significant** (affects UX, data model, or scope) → consult `product-manager` agent
- **Minor** (variable naming, log level, internal detail) → decide and document in a comment

### Rules

- Never merge without `pr-reviewer` approval.
- Never merge a PR that changes `docs/user_guide.md` without `product-manager` approval.
- `product-manager` creates all GitHub issues — don't create issues ad-hoc without going through requirements gathering first for non-trivial features.

---

## File layout reference

```
bot/
  __main__.py          # entry point — wires deps, starts polling
  bot.py               # Bot + Dispatcher factories
  config.py            # pydantic-settings Config
  db.py                # async engine + session factory
  exceptions.py        # all domain exceptions
  middleware.py        # DependencyMiddleware — DI wiring
  scheduler.py         # APScheduler jobs for due/auto-resend reminders
  handlers/
    messages.py        # main router: text, photo, document
    links.py           # link action callbacks (summary, save, remind)
    reminders.py       # reminder FSM + snooze/ack callbacks
    commands.py        # /start /list /search /reminders /cancel
    ideas.py           # /ideas command
    voice.py           # voice message transcription + routing
  services/
    classifier.py      # message type classification (LINK/TASK/NOTE/IDEA/MEDIA)
    claude_client.py   # Anthropic API wrapper
    link_service.py    # link save + on-demand summarization
    reminder_service.py
    time_parser.py     # natural-language time parsing via Claude
    idea_service.py    # idea save (tags + complexity) + suggestions
    task_service.py
    note_service.py
    list_service.py    # paginated listing + full-text search
    media_service.py   # photo/file processing (Vision + Drive)
    drive_service.py   # Google Drive upload wrapper
    scraper.py         # HTTP page fetcher
    transcription_service.py  # Groq Whisper wrapper
    vision_service.py  # Claude Vision wrapper
  repositories/
    item_repository.py
    reminder_repository.py
    idea_repository.py
  models/
    base.py            # UUIDMixin, TimestampMixin
    item.py            # Item + ItemType enum
    reminder.py        # Reminder
    idea.py            # Idea + IdeaComplexity + IdeaEffort enums
  middlewares/
    auth.py            # AuthMiddleware — ALLOWED_USER_IDS whitelist
  utils/
    text.py            # extract_url() and other pure text helpers
alembic/               # migrations
tests/
  conftest.py          # shared fixtures: fake_config, db_session
  unit/                # fast, mocked tests
  integration/         # service+repository tests with in-memory SQLite
docs/
  architecture.md      # full technical architecture guide
  user_guide.md        # user-facing feature documentation (Russian)
```
