# Contributing to tg-smart-inbox

Thank you for your interest in contributing! This document outlines the process and standards for contributing to this project.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Commit Convention](#commit-convention)
- [Pull Request Process](#pull-request-process)
- [Code Style](#code-style)
- [Updating Documentation](#updating-documentation)
- [Reporting Bugs](#reporting-bugs)
- [Suggesting Features](#suggesting-features)

---

## Code of Conduct

Be respectful and constructive. We are all here to build something useful together.

---

## Getting Started

1. **Fork** the repository and clone your fork
2. Create a virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e ".[dev]"
   ```
3. Copy `.env.example` to `.env` and fill in your credentials
4. Apply database migrations:
   ```bash
   alembic upgrade head
   ```
5. Run tests to confirm everything works:
   ```bash
   make coverage
   ```

---

## Development Workflow

1. Pick an open issue (or create one describing what you want to do)
2. Create a branch from `main`:
   ```bash
   git checkout -b feat/your-feature-name
   # or
   git checkout -b fix/bug-description
   ```
3. Make your changes with logical, focused commits
4. Run all checks before pushing:
   ```bash
   make format    # ruff format .
   make lint      # ruff check .
   make coverage  # pytest --cov; fails if coverage < 80%
   ```
5. Push your branch and open a Pull Request

---

## Commit Convention

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short description>

[optional body]
```

**Types:**
| Type | When to use |
|---|---|
| `feat` | New feature |
| `fix` | Bug fix |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `test` | Adding or updating tests |
| `docs` | Documentation changes only |
| `chore` | Dependency updates, build changes, tooling |

**Examples:**
```
feat(classifier): add idea detection to message classifier
fix(reminders): handle timezone edge case in scheduler
docs(architecture): update DB schema after migration
```

Always reference the relevant issue number: `feat: add snooze for reminders (#39)`.

---

## Pull Request Process

1. Make sure your PR addresses a single concern (one issue = one PR)
2. Write a clear PR description: **what** you changed and **why**
3. Ensure all checks pass:
   ```bash
   make format && make lint && make coverage
   ```
4. Update documentation if your change affects user-visible behaviour or architecture (see [Updating Documentation](#updating-documentation))
5. Request a review — at least one approval is required before merging
6. PRs are merged with **squash merge**; make sure your PR title follows the commit convention

---

## Code Style

- **Formatter:** [Ruff](https://docs.astral.sh/ruff/) (`ruff format .`)
- **Linter:** Ruff (`ruff check .`)
- **Type hints:** Required for all function signatures
- **Docstrings:** Required for all public functions and classes (one-line, imperative mood, Google style)
- **Line length:** 100 characters
- **Python version:** 3.11+ syntax (`X | Y` unions, `match`, etc.)

The architecture follows a strict **3-layer pattern** (Handler → Service → Repository). Read [`CLAUDE.md`](CLAUDE.md) for the full coding guidelines before writing any code.

---

## Updating Documentation

**If your change affects anything described in the docs, update the docs in the same PR.**

| What changed | File(s) to update |
|---|---|
| New or changed bot command, button, or user flow | [`docs/user_guide.md`](docs/user_guide.md) |
| New service, repository, DB schema, or config variable | [`docs/architecture.md`](docs/architecture.md) |
| New service, handler, or major structural change | Both `docs/architecture.md` and the file layout in [`CLAUDE.md`](CLAUDE.md) |
| New coding convention or tooling change | [`CLAUDE.md`](CLAUDE.md) and/or [`CONTRIBUTING.md`](CONTRIBUTING.md) |
| Project overview or setup instructions | [`README.md`](README.md) |

When in doubt, err on the side of updating — outdated documentation is worse than no documentation.

---

## Reporting Bugs

Open a [GitHub Issue](https://github.com/krabbi/tg-smart-inbox/issues/new) with:

- A clear, descriptive title
- Steps to reproduce
- Expected vs. actual behavior
- Your environment (OS, Python version)
- Relevant logs or screenshots

---

## Suggesting Features

Open a [GitHub Issue](https://github.com/krabbi/tg-smart-inbox/issues/new) with:

- A clear description of the problem you're solving
- Your proposed solution
- Alternatives you considered

Large features should be discussed in an issue before a PR is opened.

---

Thank you for contributing!
