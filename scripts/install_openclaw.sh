#!/usr/bin/env bash
# Clone and build OpenClaw gateway (peer dependency, not vendored in git).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR="$ROOT/vendor/openclaw"
PLUGIN_SRC="$ROOT/openclaw-plugin/manus-bridge"
REF="${OPENCLAW_REF:-main}"

if [[ ! -d "$VENDOR/.git" ]]; then
  echo "Cloning OpenClaw → $VENDOR"
  mkdir -p "$ROOT/vendor"
  git clone --depth 1 --branch "$REF" https://github.com/openclaw/openclaw.git "$VENDOR"
else
  echo "OpenClaw already cloned: $VENDOR"
fi

echo "Installing OpenClaw dependencies (pnpm)…"
cd "$VENDOR"
if command -v corepack >/dev/null 2>&1; then
  corepack enable
fi
pnpm install --frozen-lockfile 2>/dev/null || pnpm install
pnpm build

echo "Installing manus-bridge plugin…"
mkdir -p "$VENDOR/extensions"
rm -rf "$VENDOR/extensions/manus-bridge"
cp -a "$PLUGIN_SRC" "$VENDOR/extensions/manus-bridge"

echo "✓ OpenClaw ready: $VENDOR"
