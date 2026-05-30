# Coding Patterns — tg-smart-inbox

Detailed code patterns for the 3-layer architecture. Read this when implementing features.
For the quick summary see `CLAUDE.md`.

---

## Handler pattern

Handlers are thin: validate input, call one service, reply to user. No business logic.

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

### Callback handler pattern

```python
@router.callback_query(F.data.startswith("prefix:"))
async def cb_handler(
    callback: CallbackQuery,
    some_service: SomeService | None = None,
) -> None:
    """One-line docstring."""
    await callback.answer()
    if callback.message is None or callback.from_user is None:
        return
    if some_service is None:
        await callback.message.answer("Сервис временно недоступен.")
        return
    # ... call service, reply to user ...
```

### Optional services

Services that depend on external credentials (`transcription_service`, `media_service`) are
injected as `None` when not configured. Always guard before use:

```python
async def handle_voice(message: Message, transcription_service: TranscriptionService | None = None) -> None:
    if transcription_service is None:
        await message.answer("Голосовые сообщения не настроены.")
        return
    ...
```

### HTML rendering

When using `parse_mode="HTML"`, always escape Claude-sourced or user-sourced content:

```python
import html

text = f"📋 <b>{html.escape(summary.title)}</b>\n\n{html.escape(summary.body)}"
await message.edit_text(text, parse_mode="HTML")
```

---

## Service pattern

Services own all business logic and transaction boundaries. No Telegram API calls.

```python
class LinkService:
    """Processes incoming links: saves to DB and prepares user response."""

    def __init__(self, item_repo: ItemRepository, claude: ClaudeClient) -> None:
        self._repo = item_repo
        self._claude = claude

    async def do_something(self, item_id: uuid.UUID, user_id: int) -> SomeResult:
        """One-line imperative docstring."""
        record = await self._repo.get_by_id_for_user(item_id, user_id)
        if record is None:
            return SomeResult(ok=False)
        # ... logic ...
        await self._session.commit()
        return SomeResult(ok=True)
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

## Repository pattern

Repositories are the only layer with `AsyncSession`. Use `flush()` + `refresh()`, never `commit()`.

```python
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

    async def get_by_id_for_user(self, record_id: uuid.UUID, user_id: int) -> Record | None:
        """Return record if it belongs to user_id, else None."""
        result = await self._session.execute(
            select(Record)
            .join(Item, Record.item_id == Item.id)
            .where(Record.id == record_id, Item.user_id == user_id)
        )
        return result.scalar_one_or_none()
```

---

## Result objects

Services return frozen dataclasses defined in the same file as the service:

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

`DependencyMiddleware` in `bot/middleware.py` builds and injects all services per-request:

```python
async def __call__(self, handler, event, data):
    async with self._factory() as session:
        claude = ClaudeClient(self._config)
        item_repo = ItemRepository(session)
        data["link_service"] = LinkService(session=session, item_repo=item_repo, ...)
        data["reminder_service"] = ReminderService(
            session=session, repo=ReminderRepository(session), item_repo=item_repo
        )

        # Optional — injected as None when credentials are missing
        if self._config.groq_api_key:
            data["transcription_service"] = TranscriptionService(self._config)
        else:
            data["transcription_service"] = None

        return await handler(event, data)
```

Handlers declare dependencies as keyword arguments — aiogram resolves them from `data`:

```python
async def handle_link(message: Message, link_service: LinkService) -> None: ...
```

---

## Error handling

All domain exceptions live in `bot/exceptions.py`:

```python
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

Services raise them; handlers catch them:

```python
# Handler catches:
try:
    result = await classifier.classify(text)
except ClassificationError:
    await message.answer("Не удалось обработать сообщение. Попробуй ещё раз.")
    return
```

Raw exceptions must never reach the user. Log with context before re-raising.

---

## Comments policy

Write comments only where logic is non-obvious (workarounds, tricky algorithms, API quirks).
Every public function and class needs a one-line docstring (imperative mood, Google style).

```python
# Good
async def get_pending_reminders(self, now: datetime) -> list[Reminder]:
    """Return all unsent, non-cancelled reminders due before `now`."""
    ...

# Bad — restates the code
# Commit the session
await session.commit()
```

---

## Claude API quirks

Claude sometimes wraps JSON responses in markdown code fences (` ```json ... ``` `).
Always strip them before `json.loads()`:

```python
import re

text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE).strip()
data = json.loads(text)
```
