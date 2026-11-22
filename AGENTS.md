# AGENTS.md

`sprites-py` is the Python SDK for Fly.io Sprites. The package is `src/sprites/`, with sync
(`client.py`, `sprite.py`, ...) and asyncio (`async_*.py`) APIs. It supports Python 3.9 and
later.

## Set up

```sh
python -m venv .venv && . .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Check and test

CI runs these, and every one must pass:

```sh
python -m ruff check src tests
python -m ruff format --check src tests   # python -m ruff format src tests to fix
python -m mypy src
python -m pytest
python -m build
```

Tests are in `tests/`. CI runs pytest on Python 3.9 and 3.13 on Linux, and 3.13 on macOS and
Windows, so don't use syntax or stdlib APIs newer than 3.9.

## Releases

A release PR ("Prepare vX.Y.Z release") bumps `version` in `pyproject.toml`, `__version__` in
`src/sprites/__init__.py` and adds a `CHANGELOG.md` entry. Pushing a `vX.Y.Z` tag publishes to
PyPI (`.github/workflows/publish.yml`). Feature PRs don't change the version. Don't tag unless
asked.
