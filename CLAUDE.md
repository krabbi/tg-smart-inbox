# CLAUDE.md — Architecture & Coding Guidelines

This file is the authoritative guide for all code written in this repository. Read it before writing any code. Every decision here was made intentionally — follow it consistently.

---

## Project overview

`tg-smart-inbox` is a Telegram bot that classifies and processes forwarded messages: summarizes links, creates reminders for tasks, uploads media to Google Drive, and stores ideas.

**Stack:** Python 3.11+, aiogram 3.x, SQLAlchemy async + Alembic, Claude API (Anthropic), Google Drive API, APScheduler.

---

## Architecture: 3-layer pattern

```
Handler (aiogram)  →  Service (business logic)  →  Repository (DB access)
```

### Handlers (`bot/handlers/`)
- Thin layer: validate input, call one or more services, send a Telegram response.
- No business logic. No direct DB access. No external API calls.
- One handler file per feature domain (e.g. `links.py`, `tasks.py`).

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
- External APIs (Claude, Google Drive) are wrapped in dedicated service classes (`claude_service.py`, `drive_service.py`).
- Services return result dataclasses defined alongside them (see Result objects below).

```python
# Good
class LinkService:
    """Processes incoming links: saves to DB and prepares user response."""

    def __init__(self, item_repo: ItemRepository, claude: ClaudeService) -> None:
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

Dependencies are wired at startup in `bot/__main__.py` and injected into handlers via a custom aiogram middleware.

The middleware attaches services and the session factory to the `data` dict on each update:

```python
# bot/middleware.py
class DependencyMiddleware(BaseMiddleware):
    def __init__(self, session_factory, config: Config) -> None:
        self._factory = session_factory
        self._config = config

    async def __call__(self, handler, event, data: dict) -> Any:
        async with self._factory() as session:
            data["session"] = session
            data["config"] = self._config
            # build and inject services
            item_repo = ItemRepository(session)
            data["link_service"] = LinkService(item_repo, ClaudeService(self._config))
            return await handler(event, data)
```

```python
# bot/__main__.py
init_db(config.database_url)
factory = get_session_factory()
dp.update.middleware(DependencyMiddleware(factory, config))
```

Handlers declare injected services as keyword arguments — aiogram resolves them from `data`:

```python
async def handle_link(message: Message, link_service: LinkService) -> None: ...
```

---

## Error handling

- Define all domain exceptions in `bot/exceptions.py`. Import from there in both services and handlers.
- Services raise specific domain exceptions: `ClassificationError`, `DriveUploadError`, `ReminderParseError`, etc.
- Handlers catch domain exceptions and send user-friendly Telegram messages.
- Raw exceptions must never reach the user.
- Log errors with context at the service level before re-raising.

```python
# bot/exceptions.py
class ClassificationError(Exception):
    """Raised when Claude API fails to classify a message."""

class DriveUploadError(Exception):
    """Raised when Google Drive upload fails."""
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

## File layout reference

```
bot/
  __main__.py          # entry point — wires deps, starts polling
  bot.py               # Bot + Dispatcher factories
  config.py            # pydantic-settings Config
  db.py                # async engine + session factory
  exceptions.py        # all domain exceptions
  middleware.py        # DependencyMiddleware — DI wiring
  handlers/            # one file per feature domain
  services/            # business logic + external API wrappers
  repositories/        # SQLAlchemy CRUD (flush, no commit)
  models/              # SQLAlchemy ORM models
  utils/               # shared pure helpers (no I/O)
alembic/               # migrations
tests/
  conftest.py          # shared fixtures: fake_config, db_session
  unit/                # fast, mocked tests
  integration/         # service+repository tests with in-memory SQLite
```
