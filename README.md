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
/search     — Full-text search across everything you've saved
/reminders  — View and cancel upcoming reminders
/ideas      — View your saved ideas with tags and complexity
/cancel     — Cancel any active dialog (e.g. reminder time input)
```

## Documentation

- **[Architecture Guide](docs/architecture.md)** — 3-layer design, DB schema, DI, reminder lifecycle, config reference
- **[User Guide](docs/user_guide.md)** — all features, commands, and FAQ (in Russian)

## Architecture

```
User (Telegram)
     │
     ▼
aiogram bot (Python)
     │
     ├── Claude API     — classification, summarization, time parsing, idea tags
     ├── SQLite / PostgreSQL  — items, reminders, ideas
     ├── APScheduler    — due-reminder dispatch + auto-resend every 60s
     ├── Groq Whisper   — voice transcription (optional)
     └── Google Drive   — photo/file storage (optional)
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

## Configuration

Copy `.env.example` to `.env` and fill in:

```env
TELEGRAM_BOT_TOKEN=your_token_here
ANTHROPIC_API_KEY=your_key_here

# Comma-separated Telegram user IDs allowed to use the bot (leave empty for open access)
ALLOWED_USER_IDS=123456789,987654321

# PostgreSQL password used by docker-compose
POSTGRES_PASSWORD=change_me

# Set automatically by docker-compose; override for local runs without Docker
DATABASE_URL=postgresql+asyncpg://inbox:change_me@localhost/inbox

# Optional: voice message transcription (free tier at console.groq.com)
GROQ_API_KEY=your_groq_key_here

# Optional: photo/file upload to Google Drive
GOOGLE_DRIVE_CREDENTIALS_FILE=credentials.json
GOOGLE_DRIVE_FOLDER_ID=your_folder_id_here

# Optional: dimensionality of embeddings used for semantic search (default 1536).
# Must match the size of the pgvector columns — changing it requires an Alembic migration.
EMBEDDING_DIM=1536
```

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting a PR.

## Roadmap

- [x] MVP: classify, summarize, remind, store
- [x] Voice message transcription (Groq Whisper)
- [x] Ideas with AI tags, complexity, and effort estimates
- [x] Reminder snooze (+1h / +1d) and acknowledgement
- [x] Auto-resend if reminder is not acknowledged within 5 minutes
- [ ] Morning digest with curated content
- [ ] Web dashboard for browsing saved items
- [ ] Multi-user support

## License

MIT — see [LICENSE](LICENSE)
