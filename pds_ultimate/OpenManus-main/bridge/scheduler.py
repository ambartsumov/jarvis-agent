"""
Background scheduler for the AI agent — APScheduler AsyncIOScheduler.

Jobs:
- Daily 08:00: memory consolidation + temporal decay (keeps memory fresh)
- Daily 08:00: morning digest prepared (recent memories + reminders)
- Hourly: apply gentle temporal decay to low-importance facts

Usage:
    from bridge.scheduler import start_scheduler
    await start_scheduler(owner_user_id)
"""

from __future__ import annotations

import asyncio

from loguru import logger

_scheduler_started = False
_scheduler = None


async def _run_memory_maintenance(owner_id: int) -> None:
    """Daily memory maintenance: consolidate + decay."""
    try:
        from pds_ultimate.core.memory.hierarchy import hierarchical_memory

        store = hierarchical_memory.store
        # Temporal decay: reduce importance of old unaccessed facts
        decayed = store.apply_temporal_decay(owner_id, days_old=30, decay=0.05)
        # Consolidate: merge duplicate semantic memories
        removed = store.consolidate(owner_id)
        logger.info(
            f"Scheduler: memory maintenance user={owner_id} "
            f"decayed={decayed} consolidated={removed}"
        )
    except Exception as exc:
        logger.warning(f"Scheduler: memory maintenance failed: {exc}")


async def _run_hourly_decay(owner_id: int) -> None:
    """Hourly gentle decay on low-importance memories."""
    try:
        from pds_ultimate.core.memory.hierarchy import hierarchical_memory

        store = hierarchical_memory.store
        decayed = store.apply_temporal_decay(owner_id, days_old=90, decay=0.02)
        if decayed > 0:
            logger.debug(
                f"Scheduler: hourly decay user={owner_id} n={decayed}")
    except Exception as exc:
        logger.debug(f"Scheduler: hourly decay skipped: {exc}")


def _make_morning_digest_job(owner_id: int):
    """Return a sync function for APScheduler that queues a coroutine."""

    def job():
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_prepare_morning_digest(owner_id))

    return job


def _make_maintenance_job(owner_id: int):
    def job():
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_run_memory_maintenance(owner_id))

    return job


def _make_hourly_job(owner_id: int):
    def job():
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_run_hourly_decay(owner_id))

    return job


async def _prepare_morning_digest(owner_id: int) -> None:
    """Pre-cache morning context (recent memories + upcoming events)."""
    try:
        from pds_ultimate.core.memory.hierarchy import hierarchical_memory

        # Pull last 24h memories so they're warm in cache
        recent = hierarchical_memory.store.recall_recent(
            owner_id, hours=24, limit=20)
        logger.info(
            f"Scheduler: morning digest ready user={owner_id} memories={len(recent)}"
        )
    except Exception as exc:
        logger.warning(f"Scheduler: morning digest failed: {exc}")


async def start_scheduler(owner_user_id: int) -> None:
    """Start the APScheduler AsyncIOScheduler. Call once from ws_server."""
    global _scheduler_started, _scheduler
    if _scheduler_started:
        return

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

        # Daily at 08:00: memory maintenance + morning digest
        scheduler.add_job(
            _make_maintenance_job(owner_user_id),
            trigger="cron",
            hour=8,
            minute=0,
            id="memory_maintenance",
            replace_existing=True,
        )
        scheduler.add_job(
            _make_morning_digest_job(owner_user_id),
            trigger="cron",
            hour=8,
            minute=5,
            id="morning_digest",
            replace_existing=True,
        )

        # Hourly: gentle temporal decay
        scheduler.add_job(
            _make_hourly_job(owner_user_id),
            trigger="interval",
            hours=1,
            id="hourly_decay",
            replace_existing=True,
        )

        scheduler.start()
        _scheduler = scheduler
        _scheduler_started = True
        logger.info(
            f"Scheduler: started for user={owner_user_id} "
            f"(daily maintenance@08:00, hourly decay)"
        )
    except Exception as exc:
        logger.warning(f"Scheduler: failed to start: {exc}")
