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
    result = await link_service.process(message.text, message.from_user.id)
    await message.answer(result.reply_text, reply_markup=result.keyboard)

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

```python
# Good
class LinkService:
    def __init__(self, item_repo: ItemRepository, claude: ClaudeService) -> None:
        self._repo = item_repo
        self._claude = claude

    async def process(self, url: str, user_id: int) -> LinkResult:
        """Save link and return keyboard for user actions."""
        item = await self._repo.create(user_id=user_id, type=ItemType.link, content=url)
        return LinkResult(item_id=item.id, reply_text="Saved!", keyboard=build_link_keyboard(item.id))
```

### Repositories (`bot/repositories/`)
- The only layer that holds an `AsyncSession` and runs SQLAlchemy queries.
- No business logic. Only CRUD and query operations.
- One repository class per model (e.g. `ItemRepository`, `ReminderRepository`).

```python
# Good
class ItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, user_id: int, type: ItemType, content: str) -> Item:
        """Create and persist a new Item."""
        item = Item(user_id=user_id, type=type, content=content)
        self._session.add(item)
        await self._session.commit()
        await self._session.refresh(item)
        return item
```

---

## Dependency injection

Use aiogram's middleware system to inject dependencies into handlers.

Register services and DB sessions via a custom middleware that attaches them to `data` dict:

```python
# In bot.py or middleware setup:
dp["db_session_factory"] = session_factory
dp["config"] = config

# Handler receives injected deps automatically:
async def handler(message: Message, item_service: ItemService) -> None: ...
```

Services receive their dependencies (repos, external clients) in `__init__`. Build the dependency graph at startup in `bot/__main__.py`.

---

## Error handling

- Services raise specific domain exceptions: `ClassificationError`, `DriveUploadError`, `ReminderParseError`, etc.
- Handlers catch domain exceptions and send user-friendly Telegram messages.
- Raw exceptions must never reach the user.
- Log errors with context at the service level before re-raising.

```python
# Service raises:
class ClassificationError(Exception):
    """Raised when Claude API fails to classify a message."""

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
- Use in-memory SQLite via the `db_session` fixture from `conftest.py`.
- External APIs (Claude, Drive) are still mocked.
- Test the full Handler → Service → Repository chain.

### Rules
- Use `pytest-asyncio` for all async tests. `asyncio_mode = "auto"` is set in `pyproject.toml`.
- Use `fake_config` and `db_session` fixtures from `tests/conftest.py`.
- Target: **≥ 80% coverage** on all new code. Run with `make coverage`.
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
make lint    # ruff check .
make format  # ruff format .
make test    # pytest
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
  handlers/            # one file per feature domain
  services/            # business logic + external API wrappers
  repositories/        # SQLAlchemy CRUD
  models/              # SQLAlchemy ORM models
  utils/               # shared pure helpers (no I/O)
alembic/               # migrations
tests/
  conftest.py          # shared fixtures: fake_config, db_session
  unit/                # fast, mocked tests
  integration/         # db tests with in-memory SQLite
```
