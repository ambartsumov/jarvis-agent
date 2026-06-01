#!/usr/bin/env bash
# Jarvis Agent — start full hybrid stack
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PDS="$ROOT/pds_ultimate"
AGENT_ROOT="$ROOT"
MANUS="$PDS/OpenManus-main"
OPENCLAW_DIR="${OPENCLAW_DIR:-$ROOT/vendor/openclaw}"
VENV="${VENV:-$PDS/.venv}"
PYTHON="${PYTHON_BIN:-$VENV/bin/python}"

export PYTHONPATH="$VENV/lib/python3.12/site-packages:$AGENT_ROOT:$MANUS"
export PDS_ULTIMATE_DIR="$PDS"
export PDS_BRIDGE_MODE=1
export OPENCLAW_TELEGRAM=1
export MANUS_BRIDGE_WS="${MANUS_BRIDGE_WS:-ws://127.0.0.1:8765/manus}"

if [[ -f "$PDS/.env" ]]; then
  set -a && source "$PDS/.env" && set +a
fi
export TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-${TG_BOT_TOKEN:-}}"
export TG_PROXY="${TG_PROXY:-http://127.0.0.1:10809}"
export HTTP_PROXY="$TG_PROXY"
export HTTPS_PROXY="$TG_PROXY"

"$PYTHON" "$ROOT/scripts/render_openclaw_config.py"
"$PYTHON" "$PDS/scripts/gen_openmanus_config.py"

pkill -f "bridge.ws_server" 2>/dev/null || true
pkill -f "pds_ultimate.main" 2>/dev/null || true
pkill -f "openclaw.mjs gateway" 2>/dev/null || true
sleep 1

mkdir -p "$PDS/data"
cd "$AGENT_ROOT"
nohup "$PYTHON" -m pds_ultimate.main >> "$PDS/data/pds_main.log" 2>&1 &

for _ in $(seq 1 40); do
  ss -ltn 2>/dev/null | grep -q ':8765 ' && break
  sleep 1
done

if [[ ! -d "$OPENCLAW_DIR" ]]; then
  echo "OpenClaw not found. Run: bash $ROOT/scripts/install_openclaw.sh"
  exit 1
fi

export OPENCLAW_CONFIG_PATH="$PDS/config/openclaw.hybrid.json"
cd "$OPENCLAW_DIR"
nohup node openclaw.mjs gateway run --force --port 18789 >> "$PDS/data/openclaw.log" 2>&1 &

nohup bash "$PDS/scripts/watchdog_hybrid.sh" >> "$PDS/data/watchdog.log" 2>&1 &

echo "✓ Bridge :8765  Gateway :18789"
echo "  Logs: $PDS/data/{bridge,openclaw,pds_main}.log"
