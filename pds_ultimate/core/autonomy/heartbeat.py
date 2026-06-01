"""Heartbeat — the autonomy loop that makes the agent act on its own.

Every tick it:
  1. delivers due schedule reminders to the owner;
  2. runs due directives through the SAME agent loop (full power, owner context) and
     delivers the result.
It contains ZERO behavior templates — it only feeds stored natural-language directives
back into the agent. Behavior is entirely defined by what the owner told the agent.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Awaitable, Callable

from pds_ultimate.config import config, logger
from pds_ultimate.core.autonomy.store import autonomy_store

Notifier = Callable[[int, str], Awaitable[None]]


class Heartbeat:
    def __init__(self) -> None:
        self._notifier: Notifier | None = None
        self._task: asyncio.Task | None = None
        self._running = False
        self.interval = config.limits.heartbeat_sec

    def set_notifier(self, notifier: Notifier) -> None:
        self._notifier = notifier

    async def _notify(self, owner_id: int, text: str) -> None:
        if self._notifier:
            try:
                await self._notifier(owner_id, text)
            except Exception as exc:
                logger.warning(f"Heartbeat notify failed: {exc}")

    async def tick(self) -> None:
        now = time.time()

        # 1. Schedule reminders
        for ev in autonomy_store.due_reminders(now):
            when = datetime.fromtimestamp(ev.start_at).strftime("%H:%M") if ev.start_at else ""
            msg = f"🔔 Напоминание: {ev.title}"
            if when:
                msg += f" (в {when})"
            if ev.notes:
                msg += f"\n{ev.notes}"
            await self._notify(ev.owner_id, msg)
            autonomy_store.mark_reminder_delivered(ev.id)

        # 2. Due directives — run them through the agent autonomously
        due = autonomy_store.due_directives(now)
        if due:
            from pds_ultimate.core.agent.ethan import agent

            for d in due:
                # Mark first to avoid double-execution if a tick overlaps
                autonomy_store.mark_directive_ran(d.id)
                try:
                    task_text = (
                        f"[АВТОНОМНОЕ ИСПОЛНЕНИЕ ДИРЕКТИВЫ #{d.id}] "
                        f"Выполни постоянное распоряжение владельца и пришли результат:\n{d.text}"
                    )
                    result = await agent.run(d.owner_id, task_text)
                    answer = (result.answer or "").strip()
                    if answer:
                        await self._notify(d.owner_id, f"🤖 {answer}")
                except Exception as exc:
                    logger.warning(f"Directive #{d.id} run failed: {exc}")

    async def _loop(self) -> None:
        logger.info(f"💓 Heartbeat started (interval={self.interval}s)")
        while self._running:
            try:
                await self.tick()
            except Exception as exc:
                logger.debug(f"Heartbeat tick error: {exc}")
            await asyncio.sleep(self.interval)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        logger.info("💓 Heartbeat stopped")


heartbeat = Heartbeat()
