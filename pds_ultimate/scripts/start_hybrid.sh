#!/usr/bin/env bash
# Hybrid launcher: OpenManus (Python brain) + OpenClaw (Telegram/channels)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AGENT_ROOT="$(cd "$ROOT/.." && pwd)"
MANUS_DIR="$ROOT/OpenManus-main"
OPENCLAW_DIR="$ROOT/openclaw-main (1)/openclaw-main"
BRIDGE_HOST="${MANUS_BRIDGE_HOST:-127.0.0.1}"
BRIDGE_PORT="${MANUS_BRIDGE_PORT:-8765}"
export MANUS_BRIDGE_WS="ws://${BRIDGE_HOST}:${BRIDGE_PORT}/manus"
export PYTHONPATH="${AGENT_ROOT}:${MANUS_DIR}:${PYTHONPATH:-}"
export PDS_ULTIMATE_DIR="$ROOT"
export PDS_DEFAULT_USER_ID="${TG_OWNER_ID:-1129704360}"
export PDS_BRIDGE_MODE=1

echo "═══════════════════════════════════════════════════════════"
echo "  Hybrid: OpenManus (brain) + OpenClaw (Telegram/channels)"
echo "  WS: $MANUS_BRIDGE_WS"
echo "═══════════════════════════════════════════════════════════"

# 1. OpenManus bridge
echo "[1/2] Starting OpenManus bridge..."
cd "$MANUS_DIR"
python3 -m bridge.ws_server &
BRIDGE_PID=$!
sleep 1.5
echo "  bridge pid=$BRIDGE_PID ws=$MANUS_BRIDGE_WS"

# 2. OpenClaw gateway (Telegram via manus-bridge plugin)
echo "[2/2] Starting OpenClaw gateway..."
cd "$OPENCLAW_DIR"
export OPENCLAW_CONFIG="${OPENCLAW_CONFIG:-$ROOT/config/openclaw.hybrid.json}"
export TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-${TG_BOT_TOKEN:-}}"

if [[ ! -f "$OPENCLAW_CONFIG" ]]; then
  echo "Config not found: $OPENCLAW_CONFIG"
  exit 1
fi

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "Set TELEGRAM_BOT_TOKEN or TG_BOT_TOKEN"
  exit 1
fi

# Requires built openclaw (pnpm install && pnpm build in openclaw dir)
node openclaw.mjs gateway run --config "$OPENCLAW_CONFIG"
