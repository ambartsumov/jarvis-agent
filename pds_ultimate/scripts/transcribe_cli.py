#!/usr/bin/env python3
"""CLI for OpenClaw media-understanding — uses persistent STT server when available."""
from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT.parent
for p in (str(AGENT), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("PDS_ULTIMATE_DIR", str(ROOT))
SOCK = os.environ.get("PDS_STT_SOCKET", str(ROOT / "data" / "stt.sock"))


def _via_socket(media_path: str) -> str | None:
    sock_path = Path(SOCK)
    if not sock_path.exists():
        return None
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(30)
        s.connect(str(sock_path))
        s.sendall(f"{media_path}\n".encode())
        data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\n" in data:
                break
        s.close()
        text = data.decode().strip()
        if text.startswith("[STT error"):
            return None
        return text
    except OSError:
        return None


def _direct(media_path: str) -> str:
    from pds_ultimate.core.speech_engine import speech_engine

    return speech_engine.transcribe(media_path, language="ru").strip()


def main() -> int:
    if len(sys.argv) < 2:
        print("", end="")
        return 1
    media_path = sys.argv[1]
    try:
        text = _via_socket(media_path)
        if text is None:
            text = _direct(media_path)
        print(text)
        return 0 if text else 1
    except Exception as exc:
        print(f"[STT error: {exc}]", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
