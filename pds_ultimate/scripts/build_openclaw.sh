#!/usr/bin/env bash
set -euo pipefail

OPENCLAW_DIR="$(cd "$(dirname "$0")/../openclaw-main (1)/openclaw-main" && pwd)"
LOG="$(dirname "$OPENCLAW_DIR")/../data/openclaw-build.log"

cat > "$OPENCLAW_DIR/.npmrc" <<'EOF'
fetch-timeout=3600000
fetch-retries=20
fetch-retry-mintimeout=30000
fetch-retry-maxtimeout=3600000
network-timeout=3600000
network-concurrency=2
optional=false
supportedArchitectures.os=linux
supportedArchitectures.cpu=x64
EOF

export npm_config_fetch_timeout=3600000
export npm_config_fetch_retries=20
export npm_config_fetch_retry_maxtimeout=3600000
export PNPM_NETWORK_CONCURRENCY=2

cd "$OPENCLAW_DIR"
echo "OpenClaw build $(date)" | tee "$LOG"

for i in $(seq 1 20); do
  echo "[install $i/20] $(date +%H:%M:%S)" | tee -a "$LOG"
  if pnpm install 2>&1 | tee -a "$LOG"; then
    echo "INSTALL_OK $(date)" | tee -a "$LOG"
    break
  fi
  [[ $i -eq 20 ]] && { echo "INSTALL FAILED" | tee -a "$LOG"; exit 1; }
  sleep 15
done

echo "[build] $(date +%H:%M:%S)" | tee -a "$LOG"
pnpm build 2>&1 | tee -a "$LOG"

[[ -d dist ]] && echo "✓ OpenClaw built $(date)" | tee -a "$LOG" || { echo "✗ no dist/" | tee -a "$LOG"; exit 1; }
