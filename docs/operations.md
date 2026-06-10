# Operations Guide — tg-smart-inbox

Running, deploying, and testing the bot locally and in production.

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

---

## Running with Docker

```bash
# Production (PostgreSQL + bot pulled from GHCR + Watchtower auto-updater)
POSTGRES_PASSWORD=secret GHCR_USER=... GHCR_TOKEN=... docker compose --profile prod up -d

# Development (hot-reload, source mounted)
POSTGRES_PASSWORD=secret docker compose --profile dev up
```

### Web UI companion (`web` profile)

```bash
# 1. Build the frontend SPA (requires Node 18+, or use a one-off container):
cd frontend
docker run --rm -v "$PWD":/app -w /app node:20-alpine sh -c "npm install && npm run build"
cd ..

# 2. Start FastAPI + nginx (db starts automatically; the bot is not touched):
docker compose --profile web up -d --build
```

Requirements: `JWT_SECRET` must be set in `.env`; nginx serves `./frontend/dist`
(bind mount — rebuilding the frontend is picked up without a container restart).
The host port is `NGINX_PORT` (default `4000`). The Telegram Login Widget only
works on a domain linked to the bot via BotFather `/setdomain` — not on a raw IP.
See [`docs/architecture.md`](architecture.md) for the full web stack reference.

TLS termination is deployment-specific and intentionally not part of the repo:
add a `docker-compose.override.yml` next to `docker-compose.yml` (auto-merged by
Docker Compose, ignored by git) that publishes `443` and mounts certificates plus
an extra nginx `server` block.

The dev profile mounts `./bot` as a volume and uses `watchfiles` to restart on
any Python file change. It still builds the image locally from the `dev` stage
of the `Dockerfile`.

The prod profile does **not** build locally — it pulls the pre-built image
`ghcr.io/krabbi/tg-smart-inbox:latest` published by the GitHub Actions workflow.
Alongside `bot`, the profile starts a `watchtower` service (`containrrr/watchtower`)
that polls GHCR every 5 minutes and automatically pulls + restarts the `bot` container
when a new image digest is available. Watchtower is scoped via
`WATCHTOWER_LABEL_ENABLE=true` to update only containers with the
`com.centurylinklabs.watchtower.enable=true` label, so the `db` service is left
untouched. Watchtower authenticates against GHCR using `GHCR_USER` and `GHCR_TOKEN`
(a Personal Access Token with `read:packages` scope) and runs with
`WATCHTOWER_CLEANUP=true` so old image layers are removed after each update.

The prod `bot` service mounts two Google Drive OAuth files from the host directory
that contains `docker-compose.yml`:

- `./credentials.json:/app/credentials.json:ro` — OAuth 2.0 client secrets, read-only.
- `./token.json:/app/token.json` — user token persisted between runs, read-write so the
  Google OAuth library can rewrite it after a refresh.

Both mounts are bind mounts, so the host files must exist before
`docker compose --profile prod up -d` (otherwise Docker creates an empty directory at
the source path). For deployments that do not use Drive, create empty placeholder files
(`touch credentials.json token.json`) — the bot ignores them as long as
`GOOGLE_DRIVE_FOLDER_ID` is empty.

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

## CI/CD

Continuous integration and image publishing run on GitHub Actions. The workflow is defined
in [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) and triggers on every
push to `main`. It runs three sequential jobs — each one starts only if the previous
one succeeded.

> **Operator-facing deployment guide:** see the
> [Deploying on a home server](../README.md#deploying-on-a-home-server) section in
> `README.md` for the end-to-end recipe (Docker prerequisites, `.env` setup, first
> start, Watchtower auto-updates, and the one-time GitHub workflow permissions toggle
> required for publishing).

| Job | Needs | What it does |
|-----|-------|-------------|
| `lint` | — | Checks out the repo, sets up Python 3.11, installs `pip install ".[dev]"`, runs `ruff check .`. Fails fast on style or static-analysis violations. |
| `test` | `lint` | Runs `pytest --tb=short` against in-memory SQLite. External APIs are mocked — no real keys or PostgreSQL needed. |
| `build-push` | `test` | Builds the `base` stage of `Dockerfile` and pushes `ghcr.io/krabbi/tg-smart-inbox:latest` to GHCR using the built-in `GITHUB_TOKEN`. |

For the `build-push` job to publish packages: **Settings → Actions → General →
Workflow permissions → Read and write permissions**.

A failure in `lint` skips both `test` and `build-push`. A green `main` always
corresponds to a published image.
