#!/usr/bin/env python3
"""Smoke-test critical imports for Jarvis Agent hybrid stack."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PDS = ROOT / "pds_ultimate"
MANUS = PDS / "OpenManus-main"
sys.path[:0] = [
    str(PDS / ".venv" / "lib" / "python3.12" / "site-packages"),
    str(ROOT),
    str(MANUS),
]
os.environ.setdefault("PDS_ULTIMATE_DIR", str(PDS))
os.environ.setdefault("PDS_BRIDGE_MODE", "1")


def check(label: str, fn) -> None:
    try:
        fn()
        print(f"  OK  {label}")
    except Exception as exc:
        print(f"  FAIL {label}: {exc}")
        raise


def main() -> int:
    print("Jarvis Agent import smoke test")
    check("pds_ultimate.config", lambda: __import__("pds_ultimate.config"))
    check("pds_ultimate.core.memory", lambda: __import__("pds_ultimate.core.memory.hierarchy"))
    check("bridge.ws_server", lambda: __import__("bridge.ws_server"))
    check("bridge.streaming_manus", lambda: __import__("bridge.streaming_manus"))
    check("bridge.pds_memory_mcp", lambda: __import__("bridge.pds_memory_mcp"))
    check("bridge.pds_telegram_mcp", lambda: __import__("bridge.pds_telegram_mcp"))
    check("bridge.pds_whatsapp_mcp", lambda: __import__("bridge.pds_whatsapp_mcp"))
    check("app.agent.manus", lambda: __import__("app.agent.manus"))
    print("All imports OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
