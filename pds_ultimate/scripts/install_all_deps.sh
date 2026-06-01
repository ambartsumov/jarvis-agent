#!/usr/bin/env bash
# Full dependency install — batched (fast resolver) + OpenClaw
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AGENT_ROOT="$(cd "$ROOT/.." && pwd)"
MANUS_DIR="$ROOT/OpenManus-main"
OPENCLAW_DIR="$ROOT/openclaw-main (1)/openclaw-main"
SITE="${ROOT}/.venv/lib/python3.12/site-packages"
PY="${PYTHON_BIN:-/usr/bin/python3.12}"

export PYTHONPATH="${SITE}:${AGENT_ROOT}:${MANUS_DIR}"
export PIP_DISABLE_PIP_VERSION_CHECK=1
mkdir -p "$SITE"

pip_batch() {
  echo "  → $*"
  "$PY" -m pip install --target="$SITE" --upgrade "$@" 2>&1 | tail -3
}

echo "═══════════════════════════════════════════════════════════"
echo "  FULL install (batched)"
echo "═══════════════════════════════════════════════════════════"

echo "[1/6] PDS..."
pip_batch -r "$ROOT/requirements.txt"

echo "[2/6] OpenManus core..."
pip_batch \
  "pydantic~=2.10.6" "openai~=1.66.3" "tenacity~=9.0.0" "pyyaml~=6.0.2" "loguru~=0.7.3" \
  "tiktoken~=0.9.0" "aiofiles~=24.1.0" "colorama~=0.4.6" "uvicorn~=0.34.0" "unidiff~=0.7.5" \
  "mcp~=1.5.0" "structlog~=24.4.0" "websockets~=14.0" "python-dotenv>=1.0.0" "httpx>=0.27.0" \
  "tomli>=2.0.0" "boto3~=1.37.18" "requests~=2.32.3" "beautifulsoup4~=4.13.3"

echo "[3/6] Search + browser + sandbox..."
pip_batch \
  "html2text~=2024.2.26" "googlesearch-python~=1.3.0" "baidusearch~=1.0.3" \
  "duckduckgo_search~=7.5.3" "playwright~=1.51.0" "pillow~=11.1.0" "numpy" "fastapi~=0.115.11"
rm -rf "$SITE"/browser_use "$SITE"/browser-use* 2>/dev/null || true
pip_batch "browser-use==0.1.40" || true
pip_batch daytona || true
pip_batch docker || true

echo "[4/6] ML / crawl / test..."
pip_batch "gymnasium~=1.1.1" "pytest~=8.3.5" "pytest-asyncio~=0.25.3" "setuptools~=75.8.0"
pip_batch "datasets~=3.4.1" || true
pip_batch "huggingface-hub~=0.29.2" || true
pip_batch "crawl4ai~=0.6.3" || echo "  crawl4ai skipped"

echo "[5/6] Playwright + verify..."
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}"
"$PY" -m playwright install chromium 2>&1 | tail -3 || true

export PYTHONPATH="${SITE}:${AGENT_ROOT}:${MANUS_DIR}"
"$PY" -c "
import structlog, loguru, websockets, mcp, openai, sqlalchemy, aiogram, boto3, playwright
from browser_use import Browser, BrowserConfig
from daytona import Daytona
print('  ✓ Python full stack OK')
"

PDS_ULTIMATE_DIR="$ROOT" PYTHON_BIN="$PY" "$PY" "$ROOT/scripts/gen_openmanus_config.py"

echo "[6/6] OpenClaw build..."
cat > "$OPENCLAW_DIR/.npmrc" <<'EOF'
fetch-timeout=3600000
fetch-retries=20
network-timeout=3600000
network-concurrency=2
EOF
export npm_config_fetch_timeout=3600000
export npm_config_fetch_retries=20
export PNPM_NETWORK_CONCURRENCY=2
cd "$OPENCLAW_DIR"
for i in $(seq 1 30); do
  echo "  pnpm install $i/30..."
  pnpm install && break
  sleep 15
done
pnpm build 2>&1 | tail -30
test -d dist

echo "═══════════════════════════════════════════════════════════"
echo "  ✓ FULL install complete"
echo "═══════════════════════════════════════════════════════════"
