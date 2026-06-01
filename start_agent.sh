#!/usr/bin/env bash
# Start PDS-Ultimate Ethan Agent
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="${PYTHONPATH:-}:$(pwd)"
exec /usr/bin/python3.12 -m pds_ultimate.main "$@"
