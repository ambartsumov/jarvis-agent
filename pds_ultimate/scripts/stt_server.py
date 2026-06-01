#!/usr/bin/env python3
"""Persistent Vosk STT — модель грузится один раз, ответы через unix-socket."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT.parent
for p in (str(AGENT), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("PDS_ULTIMATE_DIR", str(ROOT))

SOCK = os.environ.get("PDS_STT_SOCKET", str(ROOT / "data" / "stt.sock"))


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        line = (await reader.readline()).decode().strip()
        if not line:
            writer.write(b"\n")
            await writer.drain()
            return
        from pds_ultimate.core.speech_engine import speech_engine

        text = await asyncio.to_thread(speech_engine.transcribe, line, "ru")
        writer.write(f"{text.strip()}\n".encode())
        await writer.drain()
    except Exception as exc:
        writer.write(f"[STT error: {exc}]\n".encode())
        await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


async def main() -> None:
    from pds_ultimate.core.speech_engine import speech_engine

    await asyncio.to_thread(speech_engine._get_model, "ru")
    print("STT server: Vosk model preloaded", flush=True)

    sock_path = Path(SOCK)
    sock_path.parent.mkdir(parents=True, exist_ok=True)
    if sock_path.exists():
        sock_path.unlink()

    server = await asyncio.start_unix_server(_handle, path=str(sock_path))
    print(f"STT server listening on {sock_path}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
