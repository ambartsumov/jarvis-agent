"""Presence / busy detection — is the owner busy *right now* per calendar?

Combines Google Calendar events (real start/end) and local schedule events
(default 60-min window). Used so the agent can auto-reply on the owner's behalf
when a message arrives while the owner is occupied.
"""

from __future__ import annotations

import time
from datetime import datetime

from pds_ultimate.config import logger

_DEFAULT_WINDOW_SEC = 3600  # local events have no explicit end


def _fmt_range(start: float, end: float) -> str:
    try:
        s = datetime.fromtimestamp(start).strftime("%H:%M")
        e = datetime.fromtimestamp(end).strftime("%H:%M") if end else ""
        return f"{s}–{e}" if e else s
    except Exception:
        return ""


async def current_activity(owner_id: int) -> dict | None:
    """Return {title, start, end, range} if owner is busy now, else None."""
    now = time.time()

    # 1) Google Calendar (authoritative start/end)
    try:
        from pds_ultimate.integrations.gcal import gcal_client

        ok, _ = gcal_client.available()
        if ok:
            events = await gcal_client.list_events(days=1)
            for ev in events:
                start = ev.get("start_at", 0)
                end = ev.get("end_at", 0) or (start + _DEFAULT_WINDOW_SEC)
                if start <= now <= end:
                    return {
                        "title": ev["title"], "start": start, "end": end,
                        "range": _fmt_range(start, end), "source": "gcal",
                    }
    except Exception as exc:
        logger.debug(f"presence gcal check: {exc}")

    # 2) Local schedule events
    try:
        from pds_ultimate.core.autonomy.store import autonomy_store

        for e in autonomy_store.all_events(owner_id):
            start = e.start_at or 0
            if not start:
                continue
            end = start + _DEFAULT_WINDOW_SEC
            if start <= now <= end:
                return {
                    "title": e.title, "start": start, "end": end,
                    "range": _fmt_range(start, end), "source": "local",
                }
    except Exception as exc:
        logger.debug(f"presence local check: {exc}")

    return None
