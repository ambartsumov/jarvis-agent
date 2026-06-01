#!/usr/bin/env python3
"""Render OpenClaw hybrid config from template + environment (no secrets in git)."""

from __future__ import annotations

import json
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "config" / "openclaw.hybrid.example.json"
OUT = ROOT / "pds_ultimate" / "config" / "openclaw.hybrid.json"


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def main() -> int:
    if not TEMPLATE.is_file():
        print(f"Template missing: {TEMPLATE}", file=sys.stderr)
        return 1

    bot_token = _env("TELEGRAM_BOT_TOKEN") or _env("TG_BOT_TOKEN")
    owner_id = _env("TG_OWNER_ID") or _env("PDS_DEFAULT_USER_ID") or "0"
    proxy = _env("TG_PROXY") or _env("HTTP_PROXY") or "http://127.0.0.1:10809"
    gateway_token = _env("OPENCLAW_GATEWAY_TOKEN") or secrets.token_hex(24)
    plugin_path = str(ROOT / "openclaw-plugin" / "manus-bridge")
    transcribe = str(ROOT / "pds_ultimate" / "scripts" / "transcribe_cli.py")
    python_bin = _env("PYTHON_BIN") or "/usr/bin/python3.12"

    cfg = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    cfg["gateway"]["auth"]["token"] = gateway_token
    cfg["plugins"]["load"]["paths"] = [plugin_path]
    cfg["plugins"]["entries"]["manus-bridge"]["config"]["proxyUrl"] = proxy
    cfg["channels"]["telegram"]["botToken"] = bot_token or "REPLACE_ME"
    cfg["channels"]["telegram"]["proxy"] = proxy
    cfg["tools"]["media"]["audio"]["models"][0]["command"] = python_bin
    cfg["tools"]["media"]["audio"]["models"][0]["args"] = [transcribe, "{{MediaPath}}"]
    cfg["commands"]["ownerAllowFrom"] = [f"telegram:{owner_id}"] if owner_id != "0" else []
    if owner_id != "0":
        cfg["tools"]["elevated"]["allowFrom"]["telegram"] = [owner_id]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Rendered {OUT}")
    if not bot_token:
        print("WARN: TELEGRAM_BOT_TOKEN / TG_BOT_TOKEN not set", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
