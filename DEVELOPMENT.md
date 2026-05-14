# Development

This repository uses `uv` for local Python development.

## Setup

Install the project and development dependencies:

```bash
uv sync --dev
```

Run the test suite:

```bash
uv run pytest -q
```

## Codex Plugin Development

For Codex-specific development plugin setup, see
[codex/DEVELOPMENT.md](codex/DEVELOPMENT.md).

