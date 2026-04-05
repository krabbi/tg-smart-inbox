# Contributing to tg-smart-inbox

Thank you for your interest in contributing! This document outlines the process and standards for contributing to this project.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Commit Convention](#commit-convention)
- [Pull Request Process](#pull-request-process)
- [Code Style](#code-style)
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
4. Run tests to confirm everything works:
   ```bash
   pytest
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
4. Push your branch and open a Pull Request

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
docs(readme): update installation instructions
```

---

## Pull Request Process

1. Make sure your PR addresses a single concern (one issue = one PR)
2. Write a clear PR description: **what** you changed and **why**
3. Ensure all tests pass (`pytest`)
4. Ensure code is formatted (`ruff format .`) and linted (`ruff check .`)
5. Request a review — at least one approval is required before merging
6. Squash commits if the history is noisy

**PR title** must also follow the commit convention above.

---

## Code Style

- **Formatter:** [Ruff](https://docs.astral.sh/ruff/) (`ruff format .`)
- **Linter:** Ruff (`ruff check .`)
- **Type hints:** Required for all function signatures
- **Docstrings:** Required for public functions and classes (Google style)
- **Line length:** 100 characters

Run all checks at once:
```bash
ruff format . && ruff check .
```

We recommend setting up pre-commit hooks:
```bash
pip install pre-commit
pre-commit install
```

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
