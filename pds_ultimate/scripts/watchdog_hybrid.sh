#!/usr/bin/env bash
# Watchdog: keep OpenManus bridge + OpenClaw gateway alive
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
JARVIS_ROOT="$(cd "$ROOT/.." && pwd)"
AGENT_ROOT="$JARVIS_ROOT"
MANUS_DIR="$ROOT/OpenManus-main"
OPENCLAW_DIR="${OPENCLAW_DIR:-$JARVIS_ROOT/vendor/openclaw}"
LOG="$ROOT/data/watchdog.log"
BRIDGE_PORT="${MANUS_BRIDGE_PORT:-8765}"
GATEWAY_PORT="${OPENCLAW_GATEWAY_PORT:-18789}"
PYTHON="/usr/bin/python3.12"

export PYTHONPATH="${ROOT}/.venv/lib/python3.12/site-packages:${AGENT_ROOT}:${MANUS_DIR}"
export PDS_ULTIMATE_DIR="$ROOT"
export PDS_DEFAULT_USER_ID="${TG_OWNER_ID:-1129704360}"
export PDS_BRIDGE_MODE=1
export MANUS_BRIDGE_WS="ws://127.0.0.1:${BRIDGE_PORT}/manus"

mkdir -p "$ROOT/data"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

port_up() {
  ss -ltn 2>/dev/null | grep -q ":$1 "
}

start_bridge() {
  if port_up "$BRIDGE_PORT"; then return 0; fi
  log "Starting bridge on :$BRIDGE_PORT"
  cd "$AGENT_ROOT"
  nohup "$PYTHON" -m bridge.ws_server >> "$ROOT/data/bridge.log" 2>&1 &
  sleep 4
}

start_gateway() {
  if port_up "$GATEWAY_PORT"; then return 0; fi
  log "Starting gateway on :$GATEWAY_PORT"
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
  export TG_PROXY="${TG_PROXY:-http://127.0.0.1:10809}"
  export HTTP_PROXY="$TG_PROXY"
  export HTTPS_PROXY="$TG_PROXY"
  export OPENCLAW_CONFIG_PATH="$ROOT/config/openclaw.hybrid.json"
  export OPENCLAW_TELEGRAM=1
  cd "$OPENCLAW_DIR"
  nohup node openclaw.mjs gateway run --force --port "$GATEWAY_PORT" >> "$ROOT/data/openclaw.log" 2>&1 &
  sleep 3
}

log "Watchdog started (bridge=:$BRIDGE_PORT gateway=:$GATEWAY_PORT)"

while true; do
  start_bridge
  start_gateway
  sleep 20
done
