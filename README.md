# tg-smart-inbox

> Turn your Telegram "Saved Messages" chaos into organized, actionable knowledge.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![aiogram 3.x](https://img.shields.io/badge/aiogram-3.x-blue.svg)](https://docs.aiogram.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## The Problem

You forward links, photos, and notes to Telegram "Saved Messages" with the intention of reviewing them later. You never do. It becomes a graveyard.

## The Solution

**tg-smart-inbox** is a personal Telegram bot that acts as a smart second brain. Send it anything — a link, a photo, a task, an idea — and it will:

- **Summarize articles** on demand with key takeaways
- **Remind you** about tasks and notes at the right time, with snooze and auto-resend
- **Save files and photos** directly to your Google Drive
- **Capture ideas** with AI-extracted tags and complexity estimates, and suggest what to work on
- **Transcribe voice messages** and process them through the same pipeline
- **Search everything** you've ever sent it

A **web dashboard** companion lets you browse, search, and delete your saved items and manage reminders from any browser — authenticated via the Telegram Login Widget.

## Features

| What you send | What the bot does |
|---|---|
| 🔗 Link / article | Saves the URL; buttons: **📋 Саммари** (AI summary with key points), **🔖 Сохранить**, **⏰ Напомнить** |
| ✅ Task | Detects intent, offers to set a reminder with natural-language time input |
| 📝 Note | Classifies and saves; searchable via `/search` |
| 💡 Idea | Extracts tags, estimates complexity and effort; ask the bot "что поделать?" anytime |
| 🖼️ Photo / file | Analyses with Vision AI, uploads to Google Drive |
| 🎤 Voice message | Transcribes with Groq Whisper, then routes through the same pipeline |

## Bot Commands

```
/start      — Welcome message and overview
/list       — Browse your last 10 saved items (paginated)
/search     — Search across everything you've saved (plain or AI-powered)
/reminders  — View and cancel upcoming reminders
/ideas      — View your saved ideas with tags and complexity
/cancel     — Cancel any active dialog (e.g. reminder time input)
```

## Documentation

- **[Architecture Guide](docs/architecture.md)** — 3-layer design, DB schema, DI, reminder lifecycle, config reference
- **[User Guide](docs/user_guide.md)** — all features, commands, and FAQ (in Russian)

## Architecture

```
User (Telegram)              User (Browser)
     │                             │
     ▼                             ▼
aiogram bot (Python)         nginx reverse proxy
     │                             │
     ├── Claude API     — classification, summarization, time parsing, idea tags
     ├── SQLite / PostgreSQL  — items, reminders, ideas
     ├── APScheduler    — due-reminder dispatch + auto-resend every 60s
     ├── Groq Whisper   — voice transcription (optional)
     ├── Google Drive   — photo/file storage (optional)
     └── FastAPI web app — REST API + Telegram Login Widget auth (JWT)
              │
              └── Foldkit SPA (TypeScript) — item list/detail, reminders, search, delete
```

## Getting Started

### Prerequisites

- Python 3.11+
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- Anthropic API key
- Groq API key *(optional — for voice transcription, free at [console.groq.com](https://console.groq.com))*
- Google Drive API credentials *(optional — for photo/file upload)*

### Installation

```bash
git clone https://github.com/krabbi/tg-smart-inbox.git
cd tg-smart-inbox

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
cp .env.example .env
# Fill in your credentials in .env

alembic upgrade head
python -m bot
```

### Running with Docker (recommended)

```bash
cp .env.example .env
# Fill in your credentials in .env

# Development — hot-reload on code changes
docker compose --profile dev up

# Production
docker compose --profile prod up -d
```

## Deploying on a home server

This is the end-to-end recipe for running the bot 24/7 on your own machine
(e.g. a home server, NAS, or VPS) using the pre-built image from GitHub
Container Registry. Watchtower keeps the container up to date automatically
whenever a new `latest` tag is published by the CI workflow.

### 1. Prerequisites

- A Linux server with **Docker Engine** and the **Docker Compose plugin**
  installed (`docker compose version` should succeed).
- The repository cloned on the server:

  ```bash
  git clone https://github.com/krabbi/tg-smart-inbox.git
  cd tg-smart-inbox
  ```

  Only `docker-compose.yml` and `.env` are strictly needed at runtime — the
  bot itself runs from the GHCR image, not from the local source tree.

### 2. Prepare `.env`

Copy the example and fill in your credentials:

```bash
cp .env.example .env
```

The following variables are **required** for the `prod` profile:

| Variable | Why it's needed |
|---|---|
| `POSTGRES_PASSWORD` | Password for the local Postgres container; must be set or `docker compose` refuses to start |
| `TELEGRAM_BOT_TOKEN` | Bot API token from [@BotFather](https://t.me/BotFather) |
| `ANTHROPIC_API_KEY` | Claude API key — used for classification, summarization, idea tagging |
| `ALLOWED_USER_IDS` | Comma-separated Telegram user IDs (allowlist mode). Leave empty for open access — any Telegram user may interact with the bot. All data is always isolated per user regardless of this setting. |
| `VOYAGE_API_KEY` | Voyage AI key — required for semantic search and embedding indexing |
| `GHCR_USER` | Your GitHub username — used by Watchtower to authenticate against `ghcr.io` |
| `GHCR_TOKEN` | GitHub Personal Access Token with the **`read:packages`** scope |

To generate `GHCR_TOKEN`: GitHub → **Settings → Developer settings →
Personal access tokens → Tokens (classic) → Generate new token (classic)**,
tick **`read:packages`**, copy the value into `.env`. No other scopes are
required for pulling the public bot image.

Optional integrations (`GROQ_API_KEY` for voice transcription,
`GOOGLE_DRIVE_*` for media upload) can be left at their placeholder values if
you don't use them — the bot starts without them and the corresponding
features stay disabled.

If you enable Google Drive, place the OAuth files next to `docker-compose.yml`
on the host: `credentials.json` (downloaded from Google Cloud Console as a
**Desktop app** OAuth 2.0 Client ID) and `token.json` (auto-created on first
run after the one-time browser consent — start with an empty file:
`touch token.json`). The prod profile mounts both into the container
automatically (`/app/credentials.json` read-only, `/app/token.json`
read-write). If you don't use Drive, create empty placeholders so Docker
doesn't substitute directories for the missing files:
`touch credentials.json token.json`.

### 3. First start

Pull the published image and start the stack in the background:

```bash
docker compose --profile prod pull
docker compose --profile prod up -d
```

The `prod` profile starts five containers:

- `db` — Postgres with the `pgvector` extension
- `bot` — the Telegram bot (`ghcr.io/krabbi/tg-smart-inbox:latest`)
- `web` — FastAPI REST API for the web dashboard (same image, different entrypoint)
- `nginx` — reverse proxy: serves the Foldkit SPA and forwards `/api/*` to `web`
- `watchtower` — auto-updater (see below)

### 4. Auto-updates with Watchtower

Watchtower polls GHCR every **300 seconds** (5 minutes) by default. When the
CI workflow publishes a new `latest` digest, Watchtower pulls it, gracefully
stops the running container, and starts the new one — no manual `pull` /
`up -d` is needed on the server.

Only containers with the
`com.centurylinklabs.watchtower.enable=true` label are touched, so the `db`
container is left alone.

To change the polling interval, edit `WATCHTOWER_POLL_INTERVAL` in
`docker-compose.yml` (value is seconds). Old image layers are removed
automatically after each update (`WATCHTOWER_CLEANUP=true`).

### 5. Viewing logs

```bash
docker compose --profile prod logs -f bot
```

Use the same command with `db` or `watchtower` to inspect those containers.

### 6. One-time GitHub repo setup (publishing side)

For the CI workflow to publish images to GHCR, the repository must allow
Actions to write packages: **Settings → Actions → General → Workflow
permissions → Read and write permissions**. After enabling this, the
built-in `GITHUB_TOKEN` is enough to push to `ghcr.io/<owner>/<repo>` and no
additional repo secret is required.

This is a one-time switch; once flipped, every push to `main` triggers a
new image build and Watchtower picks it up on its next poll cycle.

## Configuration

Copy `.env.example` to `.env` and fill in:

```env
TELEGRAM_BOT_TOKEN=your_token_here
ANTHROPIC_API_KEY=your_key_here

# Access control: comma-separated Telegram user IDs.
# Non-empty → allowlist mode: only the listed IDs may use the bot.
# Empty (or omitted) → open mode: any Telegram user may use the bot.
# In both modes all data (items, reminders, settings, search) is isolated per user.
ALLOWED_USER_IDS=123456789,987654321

# PostgreSQL password used by docker-compose
POSTGRES_PASSWORD=change_me

# Set automatically by docker-compose; override for local runs without Docker
DATABASE_URL=postgresql+asyncpg://inbox:change_me@localhost/inbox

# Optional: voice message transcription (free tier at console.groq.com)
GROQ_API_KEY=your_groq_key_here

# Optional: photo/file upload to Google Drive (OAuth 2.0 — uses your personal Drive quota)
# GOOGLE_DRIVE_CREDENTIALS_FILE points to OAuth 2.0 client secrets JSON
# (Google Cloud Console → APIs & Services → Credentials → "OAuth 2.0 Client IDs",
# Desktop app). On first run the bot opens a browser for one-time consent and
# saves the resulting token to GOOGLE_DRIVE_TOKEN_FILE. The token is auto-refreshed
# on subsequent runs and must persist across container restarts (mount the path
# as a volume in Docker).
GOOGLE_DRIVE_CREDENTIALS_FILE=credentials.json
GOOGLE_DRIVE_TOKEN_FILE=token.json
GOOGLE_DRIVE_FOLDER_ID=your_folder_id_here

# Optional: semantic search (free tier at voyageai.com)
VOYAGE_API_KEY=your_voyage_key_here

# Optional: dimensionality of embeddings (default 1024, matches voyage-3.5).
# Must match the size of the pgvector columns — changing it requires an Alembic migration.
EMBEDDING_DIM=1024

# Optional: web UI companion service.
# JWT_SECRET is required only when running the web service (web/main.py validates it).
# The bot process starts without it.
JWT_SECRET=change_me_to_a_long_random_string
WEB_PORT=8000
# Host port the nginx reverse proxy is published on (web profile). Container port stays 80.
NGINX_PORT=4000
# Comma-separated list of allowed CORS origins for the web UI companion.
# Non-empty → credentialed requests are allowed from these origins only (production).
# Empty (default) → wildcard "*" without credentials is used (dev convenience).
CORS_ORIGINS=https://your-frontend-domain.example.com

# Optional: frontend Vite env var — base URL for API requests from the web UI.
# Set this in frontend/.env.local for local development (e.g. http://localhost:8000).
# In production the nginx proxy forwards /api/ so the default empty string works.
VITE_API_BASE_URL=http://localhost:8000

# Optional: frontend Vite env var — Telegram bot username (without @) used by the
# Login Widget. Set this in frontend/.env.local or in the CI/CD build environment.
# If unset, the widget renders with an empty data-telegram-login attribute and
# Telegram will reject the embed.
VITE_BOT_USERNAME=your_bot_username_here

# Required for the `prod` docker-compose profile only — used by Watchtower to
# pull ghcr.io/krabbi/tg-smart-inbox:latest. GHCR_TOKEN must have read:packages.
GHCR_USER=your_github_username_here
GHCR_TOKEN=your_github_pat_with_read_packages_scope_here
```

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting a PR.

## Roadmap

- [x] MVP: classify, summarize, remind, store
- [x] Voice message transcription (Groq Whisper)
- [x] Ideas with AI tags, complexity, and effort estimates
- [x] Reminder snooze (+1h / +1d) and acknowledgement
- [x] Auto-resend if reminder is not acknowledged within 5 minutes
- [x] Multi-user support: per-user data isolation, allowlist access control, first-use onboarding
- [x] Google Drive media upload with per-user folder isolation (v1: shared bot-owner Drive quota)
- [ ] Google Drive v2: per-user OAuth so files land in each user's own Drive
- [ ] Morning digest with curated content
- [x] Web dashboard — browse, search, and delete items; manage reminders (Telegram Login Widget + JWT)

## License

MIT — see [LICENSE](LICENSE)
