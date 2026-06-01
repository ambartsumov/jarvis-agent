#!/usr/bin/env bash
# Full stack: Python deps + OpenClaw build + launch PDS + OpenClaw gateway
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AGENT_ROOT="$(cd "$ROOT/.." && pwd)"
MANUS_DIR="$ROOT/OpenManus-main"
OPENCLAW_DIR="$ROOT/openclaw-main (1)/openclaw-main"
SITE="${ROOT}/.venv/lib/python3.12/site-packages"
PY="/usr/bin/python3.12"
LOG="${ROOT}/data/system.log"

mkdir -p "${ROOT}/data"
export PYTHONPATH="${SITE}:${AGENT_ROOT}:${MANUS_DIR}"
export PDS_ULTIMATE_DIR="$ROOT"
export PYTHON_BIN="$PY"
export MANUS_BRIDGE_WS="${MANUS_BRIDGE_WS:-ws://127.0.0.1:8765/manus}"
export OPENCLAW_CONFIG="${OPENCLAW_CONFIG:-$ROOT/config/openclaw.hybrid.json}"
export OPENCLAW_TELEGRAM=1

if [[ -f "$ROOT/.env" ]]; then set -a; source "$ROOT/.env"; set +a; fi
export TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-${TG_BOT_TOKEN:-}}"

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

stop_all() {
  pkill -f "bridge.ws_server" 2>/dev/null || true
  pkill -f "pds_ultimate.main" 2>/dev/null || true
  pkill -f "openclaw.mjs gateway" 2>/dev/null || true
  pkill -f "cursor.AppImage -m pds" 2>/dev/null || true
  rm -f "${ROOT}/data/.agent.lock"
  sleep 1
}

stop_all

# ── 1. Python ──────────────────────────────────────────────────────────────
log "═══ [1/4] Python full stack ═══"
pip_install() { "$PY" -m pip install --target="$SITE" --upgrade "$@" 2>&1 | tail -3; }

pip_install -r "$ROOT/requirements.txt"
pip_install \
  "pydantic~=2.10.6" "openai~=1.66.3" "tenacity~=9.0.0" "pyyaml~=6.0.2" "loguru~=0.7.3" \
  "tiktoken~=0.9.0" "mcp~=1.5.0" "structlog~=24.4.0" "websockets~=14.0" \
  "html2text~=2024.2.26" "googlesearch-python~=1.3.0" "baidusearch~=1.0.3" \
  "duckduckgo_search~=7.5.3" "playwright~=1.51.0" "pillow~=11.1.0" "numpy" "fastapi~=0.115.11" \
  "uvicorn~=0.34.0" "unidiff~=0.7.5" "docker~=7.1.0" "boto3~=1.37.18" \
  "requests~=2.32.3" "beautifulsoup4~=4.13.3" "python-dotenv>=1.0.0" "httpx>=0.27.0" \
  "tomli>=2.0.0" "google-auth>=2.30.0" "google-auth-oauthlib>=1.2.0" \
  "google-api-python-client>=2.130.0" "gymnasium~=1.1.1" "huggingface-hub~=0.29.2" \
  "datasets~=3.4.1" "setuptools~=75.8.0" "pytest~=8.3.5" "pytest-asyncio~=0.25.3"
rm -rf "$SITE"/browser_use "$SITE"/browser-use* 2>/dev/null || true
pip_install "browser-use==0.1.40" daytona
pip_install "crawl4ai~=0.6.3" || log "crawl4ai skipped"

"$PY" -m playwright install chromium 2>&1 | tail -2 || true
"$PY" "$ROOT/scripts/gen_openmanus_config.py"
"$PY" -c "
import structlog, websockets, mcp, openai, playwright
from browser_use import Browser, BrowserConfig
from daytona import Daytona
from bridge.streaming_manus import StreamingManus
print('Python OK')
" && log "✓ Python full stack"

# ── 2. OpenClaw ────────────────────────────────────────────────────────────
log "═══ [2/4] OpenClaw build ═══"
if [[ ! -d "$OPENCLAW_DIR/dist" ]]; then
  bash "$ROOT/scripts/build_openclaw.sh" 2>&1 | tee -a "$LOG"
fi
[[ -d "$OPENCLAW_DIR/dist" ]] || { log "✗ OpenClaw dist missing"; exit 1; }
log "✓ OpenClaw dist ready"

# ── 3. PDS + bridge ────────────────────────────────────────────────────────
log "═══ [3/4] PDS + OpenManus bridge ═══"
stop_all
cd "$AGENT_ROOT"
nohup "$PY" -m pds_ultimate.main >> "$LOG" 2>&1 &
sleep 4

for i in $(seq 1 30); do
  if "$PY" -c "
import asyncio,json,websockets
async def t():
    async with websockets.connect('${MANUS_BRIDGE_WS}', open_timeout=2) as ws:
        await ws.send(json.dumps({'type':'ping','id':'boot'}))
        assert json.loads(await ws.recv()).get('type')=='pong'
asyncio.run(t())
" 2>/dev/null; then
    log "✓ Bridge ${MANUS_BRIDGE_WS}"
    break
  fi
  sleep 1
done

# ── 4. OpenClaw gateway ────────────────────────────────────────────────────
log "═══ [4/4] OpenClaw Telegram gateway ═══"
if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  log "⚠ TELEGRAM_BOT_TOKEN not set — starting without Telegram"
else
  cd "$OPENCLAW_DIR"
  nohup node openclaw.mjs gateway run --config "$OPENCLAW_CONFIG" >> "$LOG" 2>&1 &
  sleep 3
  log "✓ OpenClaw gateway started"
fi

log "══════════════════════════════════════════════════════════"
log "  SYSTEM RUNNING"
log "  Bridge:  ${MANUS_BRIDGE_WS}"
log "  Log:     ${LOG}"
log "  Telegram → write to your bot"
log "══════════════════════════════════════════════════════════"
