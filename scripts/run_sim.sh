#!/usr/bin/env bash
# Run the fake µGateway on port 8080; the claim "button" is pressed automatically after 3 s.
cd "$(dirname "$0")/.."
uv run python -m simulator --port 8080 --auto-press 3 "$@"
