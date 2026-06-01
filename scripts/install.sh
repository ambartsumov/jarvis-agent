#!/usr/bin/env bash
# Jarvis Agent — one-shot local setup
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PDS="$ROOT/pds_ultimate"
VENV="${VENV:-$PDS/.venv}"
PYTHON="${PYTHON_BIN:-python3.12}"

echo "══════════════════════════════════════════════════════════"
echo "  Jarvis Agent — setup"
echo "══════════════════════════════════════════════════════════"

if [[ ! -f "$PDS/.env" ]]; then
  cp "$PDS/.env.example" "$PDS/.env"
  echo "Created $PDS/.env — edit secrets before start"
fi

echo "[1/4] Python venv + deps"
"$PYTHON" -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install -U pip wheel
pip install -r "$PDS/requirements.txt"

echo "[2/4] OpenManus config"
export PDS_ULTIMATE_DIR="$PDS"
export PYTHON_BIN="$VENV/bin/python"
"$VENV/bin/python" "$PDS/scripts/gen_openmanus_config.py"

echo "[3/4] OpenClaw gateway (optional, ~5 min)"
if [[ "${SKIP_OPENCLAW:-}" != "1" ]]; then
  bash "$ROOT/scripts/install_openclaw.sh"
fi

echo "[4/4] Render OpenClaw hybrid config"
set -a && source "$PDS/.env" && set +a
"$VENV/bin/python" "$ROOT/scripts/render_openclaw_config.py"

echo ""
echo "Done. Start: bash $ROOT/scripts/start.sh"
