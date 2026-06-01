"""Dedicated asyncio loop in a background thread — fixes Telethon 'loop must not change'."""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Coroutine, TypeVar

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_ready = threading.Event()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop, _thread
    if _loop is not None and _loop.is_running():
        return _loop

    def _runner() -> None:
        global _loop
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
        _ready.set()
        _loop.run_forever()

    _ready.clear()
    _thread = threading.Thread(target=_runner, name="pds-mcp-async", daemon=True)
    _thread.start()
    _ready.wait(timeout=30)
    if _loop is None:
        raise RuntimeError("Failed to start PDS MCP async loop")
    return _loop


def run_coroutine(coro: Coroutine[Any, Any, T], timeout: float = 120) -> T:
    loop = _ensure_loop()
    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    return fut.result(timeout=timeout)
