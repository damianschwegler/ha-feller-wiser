#!/usr/bin/env bash
# Dev-container / fresh clone setup: install uv and the dev dependencies.
set -e
cd "$(dirname "$0")/.."
if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi
uv sync
uv run pre-commit install || true
