# tg-smart-inbox

> Turn your Telegram "Saved Messages" chaos into organized, actionable knowledge.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![aiogram 3.x](https://img.shields.io/badge/aiogram-3.x-blue.svg)](https://docs.aiogram.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## The Problem

You forward links, photos, and notes to Telegram "Saved Messages" with the intention of reviewing them later. You never do. It becomes a graveyard.

## The Solution

**tg-smart-inbox** is a personal Telegram bot that acts as a smart second brain. Send it anything — a link, a photo, a task, an idea — and it will:

- **Summarize articles** automatically and let you act on them
- **Remind you** about tasks and notes at the right time
- **Save files and photos** directly to your Google Drive
- **Capture ideas** and help you rediscover them when you need inspiration
- **Search everything** you've ever sent it

## Features

| What you send | What the bot does |
|---|---|
| 🔗 Link / article | Fetches content, generates a concise summary, offers `[Read summary]` / `[Remind me later]` |
| 📝 Task or note | Detects intent, asks if you want a reminder, schedules it |
| 🖼️ Photo / file | Uploads to Google Drive, sends back a shareable link |
| 💡 Idea | Classifies as an idea, stores it — ask the bot "what should I work on?" anytime |
| 🎤 Voice message | Transcribes with Whisper, then processes the text through the same pipeline |
| 💬 Any text | Classifies intelligently and stores with full-text search |

## Bot Commands

```
/list       — Browse your saved items by category
/search     — Full-text search across everything you've saved
/reminders  — View and manage upcoming reminders
/ideas      — View your saved ideas and get AI-powered suggestions
```

## Architecture

```
User (Telegram)
     │
     ▼
aiogram bot (Python)
     │
     ├── Claude API (classification + summarization + ideas)
     ├── SQLite / PostgreSQL (notes, reminders, ideas)
     └── Google Drive API (file storage)
```

## Getting Started

### Prerequisites

- Python 3.11+
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- Anthropic API key
- Google Drive API credentials *(optional — for photo/file upload)*
- Groq API key *(optional — for voice transcription, free at [console.groq.com](https://console.groq.com))*

### Installation

```bash
git clone https://github.com/krabbi/tg-smart-inbox.git
cd tg-smart-inbox

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
cp .env.example .env
# Fill in your credentials in .env
```

### Running

```bash
python -m bot
```

## Configuration

Copy `.env.example` to `.env` and fill in:

```env
TELEGRAM_BOT_TOKEN=your_token_here
ANTHROPIC_API_KEY=your_key_here
DATABASE_URL=sqlite:///data/inbox.db

# Optional: voice message transcription (free tier at console.groq.com)
GROQ_API_KEY=your_groq_key_here

# Optional: photo/file upload to Google Drive
GOOGLE_DRIVE_CREDENTIALS_FILE=credentials.json
GOOGLE_DRIVE_FOLDER_ID=your_folder_id_here
```

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting a PR.

## Roadmap

- [x] MVP: classify, summarize, remind, store
- [x] Voice message transcription (Groq Whisper Large v3)
- [ ] Morning digest with curated content
- [ ] Web dashboard for browsing saved items
- [ ] Multi-user support

## License

MIT — see [LICENSE](LICENSE)
