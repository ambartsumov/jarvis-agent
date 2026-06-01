"""Per-user cancellation registry — powers the /stop command."""

from __future__ import annotations

import asyncio


class CancellationRegistry:
    def __init__(self) -> None:
        self._events: dict[int, asyncio.Event] = {}

    def begin(self, user_id: int) -> asyncio.Event:
        ev = asyncio.Event()
        self._events[user_id] = ev
        return ev

    def cancel(self, user_id: int) -> bool:
        ev = self._events.get(user_id)
        if ev and not ev.is_set():
            ev.set()
            return True
        return False

    def end(self, user_id: int) -> None:
        self._events.pop(user_id, None)

    def is_cancelled(self, user_id: int) -> bool:
        ev = self._events.get(user_id)
        return bool(ev and ev.is_set())


cancellation = CancellationRegistry()
