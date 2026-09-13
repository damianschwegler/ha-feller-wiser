#!/usr/bin/env bash
# Start a local Home Assistant instance (config/) with this integration on PYTHONPATH.
# Add the integration via the UI: Settings -> Devices & services -> Add -> "Wiser by Feller",
# host "localhost:8080" when scripts/run_sim.sh is running.
set -e
cd "$(dirname "$0")/.."
if [[ ! -f config/.HA_VERSION ]]; then
    uv run hass --config config --script ensure_config
fi
export PYTHONPATH="${PYTHONPATH}:${PWD}/custom_components"
uv run hass --config config --debug
