# Contributing

Thanks for helping! Bug reports with the diagnostics download (Settings → Devices &
services → Wiser by Feller → ⋮ → Download diagnostics) are the most useful thing you can send.

## Setup

- Open the repo in the dev container (VS Code → *Reopen in Container*), or run
  `scripts/setup.sh` locally (needs Python 3.14 and `uv`).
- `uv run pytest` runs everything against the built-in gateway simulator; no hardware needed.
- `uv run ruff check . && uv run ruff format . && uv run mypy` must be clean.
- `scripts/run_sim.sh` + `scripts/develop.sh` give you a local Home Assistant with a fake
  gateway on port 8080 for UI work.

## Pull requests

- One topic per PR, tests included.
- Keep the gateway API facts in `docs/api-notes.md` up to date when you learn something new
  from real hardware.
- User-facing text goes into `strings.json` and both `translations/*.json` files
  (English and German; Swiss spelling, no ß).
