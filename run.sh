#!/usr/bin/with-contenv bashio
set -euo pipefail

LOG_LEVEL="$(bashio::config 'log_level')"
export LOG_LEVEL
export APP_HOST="0.0.0.0"
export APP_PORT="8099"
export OPTIONS_PATH="/data/options.json"
export DATA_PATH="/data"
export ADDON_CONFIG_PATH="/config"
export HA_CONFIG_PATH="/homeassistant"

bashio::log.info "Starting Instance Entity Bridge on port ${APP_PORT}"
exec python3 -m uvicorn src.app:app --host "${APP_HOST}" --port "${APP_PORT}" --log-level "${LOG_LEVEL}"
