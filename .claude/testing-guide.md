# Testing Guide — tg-smart-inbox

Detailed testing conventions. Read this when writing tests.
For the quick summary see `CLAUDE.md`.

---

## Structure

Test file mirrors source file:
```
bot/services/classifier.py   →  tests/unit/test_classifier.py
bot/repositories/item.py     →  tests/unit/test_item_repository.py
```

---

## Unit tests (`tests/unit/`)

Mock all external dependencies. Fast — no I/O, no network.

```python
async def test_method_does_expected_thing() -> None:
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    repo = MagicMock(spec=SomeRepository)
    repo.some_method = AsyncMock(return_value=mock_value)
    svc = SomeService(session=session, repo=repo)

    result = await svc.do_something(item_id=uuid.uuid4(), user_id=1)

    repo.some_method.assert_awaited_once_with(...)
    session.commit.assert_awaited_once()
    assert result.ok is True
```

### Service test factory pattern

When a service has many tests, use a `make_service()` factory to avoid repetition:

```python
def make_service() -> tuple[MyService, MyRepository, AsyncSession]:
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    repo = MagicMock(spec=MyRepository)
    svc = MyService(session=session, repo=repo)
    return svc, repo, session


async def test_create_saves_and_commits() -> None:
    svc, repo, session = make_service()
    repo.create = AsyncMock(return_value=MagicMock(spec=MyModel))

    await svc.create(...)

    repo.create.assert_awaited_once_with(...)
    session.commit.assert_awaited_once()
```

### Mocking Claude responses

```python
mock_claude = MagicMock(spec=ClaudeClient)
mock_claude.complete = AsyncMock(return_value='{"type": "task"}')
```

---

## Integration tests (`tests/integration/`)

Test the **Service → Repository** chain against in-memory SQLite.
Use the `db_session` fixture from `tests/conftest.py`. External APIs still mocked.

```python
async def test_create_and_retrieve(db_session: AsyncSession) -> None:
    repo = ItemRepository(db_session)
    item = await repo.create(user_id=1, type=ItemType.note, content="hello")
    await db_session.commit()

    result = await repo.get_by_id(item.id)
    assert result is not None
    assert result.content == "hello"
```

---

## Rules

- `asyncio_mode = "auto"` is set in `pyproject.toml` — all async tests run automatically.
- Use `fake_config` and `db_session` fixtures from `tests/conftest.py`.
- Use `MagicMock(spec=ClassName)` — the `spec` catches attribute typos at test time.
- Use `AsyncMock` for all `async def` methods.
- Never use real API keys, tokens, or production DB in tests.
- Coverage target: **≥ 80%** on all new code. Run with `make coverage`.
- `make test` for quick iteration (no coverage threshold); CI uses `make coverage`.

---

## Running tests

```bash
make test        # fast, no coverage threshold
make coverage    # with --cov, fails if < 80%
pytest tests/unit/test_foo.py -v   # single file
pytest -k "test_name" -v           # single test
```
