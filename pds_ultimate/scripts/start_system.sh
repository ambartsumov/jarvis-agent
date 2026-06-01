#!/usr/bin/env bash
# Unified launcher: PDS memory + OpenManus bridge + OpenClaw Telegram
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AGENT_ROOT="$(cd "$ROOT/.." && pwd)"
MANUS_DIR="$ROOT/OpenManus-main"
OPENCLAW_DIR="$ROOT/openclaw-main (1)/openclaw-main"
VENV="${VENV:-$ROOT/.venv}"
SITE_PACKAGES="${VENV}/lib/python3.12/site-packages"
PYTHON="${PYTHON_BIN:-/usr/bin/python3.12}"

BRIDGE_HOST="${MANUS_BRIDGE_HOST:-127.0.0.1}"
BRIDGE_PORT="${MANUS_BRIDGE_PORT:-8765}"
export MANUS_BRIDGE_WS="ws://${BRIDGE_HOST}:${BRIDGE_PORT}/manus"
export PDS_ULTIMATE_DIR="$ROOT"
export OPENCLAW_TELEGRAM=1
export PYTHONPATH="${SITE_PACKAGES}:${AGENT_ROOT}:${MANUS_DIR}:${PYTHONPATH:-}"
export OPENCLAW_CONFIG="${OPENCLAW_CONFIG:-$ROOT/config/openclaw.hybrid.json}"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

export TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-${TG_BOT_TOKEN:-}}"

echo "═══════════════════════════════════════════════════════════"
echo "  PDS + OpenManus + OpenClaw — unified system"
echo "  WS: $MANUS_BRIDGE_WS"
echo "  Config: $OPENCLAW_CONFIG"
echo "═══════════════════════════════════════════════════════════"

if [[ ! -x "$PYTHON" ]]; then
  echo "Python not found: $PYTHON"
  exit 1
fi

if [[ ! -d "$SITE_PACKAGES/structlog" ]] || [[ "${FORCE_DEPS:-}" == "1" ]]; then
  echo "Installing FULL Python deps..."
  FORCE_DEPS=1 bash "$ROOT/scripts/install_all_deps.sh" || {
    echo "Full install failed — retry: FORCE_DEPS=1 bash $ROOT/scripts/install_all_deps.sh"
    exit 1
  }
fi

export PYTHON_BIN="$PYTHON"
"$PYTHON" "$ROOT/scripts/gen_openmanus_config.py"

stop_old() {
  pkill -f "bridge.ws_server" 2>/dev/null || true
  pkill -f "pds_ultimate.main" 2>/dev/null || true
  pkill -f "openclaw.mjs gateway" 2>/dev/null || true
  sleep 0.5
}

wait_bridge() {
  local tries=30
  while (( tries-- > 0 )); do
    if "$PYTHON" -c "
import asyncio, json, os, websockets
async def t():
    url = f\"ws://{os.environ.get('MANUS_BRIDGE_HOST','127.0.0.1')}:{os.environ.get('MANUS_BRIDGE_PORT','8765')}/manus\"
    async with websockets.connect(url, open_timeout=2) as ws:
        await ws.send(json.dumps({'type':'ping','id':'health'}))
        r = await asyncio.wait_for(ws.recv(), timeout=5)
        assert json.loads(r).get('type')=='pong'
asyncio.run(t())
" 2>/dev/null; then
      echo "  ✓ Bridge healthy"
      return 0
    fi
    sleep 1
  done
  echo "  ✗ Bridge did not respond on $MANUS_BRIDGE_WS"
  return 1
}

cleanup() {
  echo ""
  echo "Shutting down..."
  [[ -n "${PDS_PID:-}" ]] && kill "$PDS_PID" 2>/dev/null || true
  [[ -n "${OPENCLAW_PID:-}" ]] && kill "$OPENCLAW_PID" 2>/dev/null || true
  stop_old
}
trap cleanup EXIT INT TERM

stop_old

echo "[1/4] Starting PDS backend (DB + memory + bridge)..."
cd "$AGENT_ROOT"
"$PYTHON" -m pds_ultimate.main &
PDS_PID=$!
sleep 2

echo "[2/4] Waiting for OpenManus bridge..."
wait_bridge

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "WARN: TELEGRAM_BOT_TOKEN / TG_BOT_TOKEN not set — OpenClaw Telegram disabled"
elif [[ "${OPENCLAW_SKIP:-}" == "1" ]]; then
  echo "[3/4] OpenClaw skipped (OPENCLAW_SKIP=1) — use full stack without this flag"
else
  echo "[3/4] OpenClaw gateway..."
  if [[ ! -d "$OPENCLAW_DIR/dist" ]]; then
    echo "  OpenClaw not built — running full install..."
    FORCE_DEPS=1 bash "$ROOT/scripts/install_all_deps.sh"
  fi

  cd "$OPENCLAW_DIR"
  export OPENCLAW_CONFIG_PATH="$OPENCLAW_CONFIG"
  node openclaw.mjs gateway run --force --port 18789 &
  OPENCLAW_PID=$!
  sleep 2
  echo "  ✓ OpenClaw pid=$OPENCLAW_PID"
fi

echo "[4/4] System running"
echo "  PDS pid=$PDS_PID  bridge=$MANUS_BRIDGE_WS"
echo "  Telegram → write to your bot"
echo "  Stop: Ctrl+C"
echo "═══════════════════════════════════════════════════════════"

wait "$PDS_PID"
