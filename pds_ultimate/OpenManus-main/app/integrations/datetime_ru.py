"""Russian/ISO datetime parsing for calendar tool."""

from __future__ import annotations

import re
from datetime import datetime, timedelta


def parse_datetime(value: str) -> float:
    if not value:
        return 0.0
    raw = value.strip()
    low = raw.lower()
    now = datetime.now()
    hour, minute = 10, 0
    tm = re.search(r"(\d{1,2})[:.](\d{2})", low)
    if tm:
        hour, minute = int(tm.group(1)), int(tm.group(2))

    base: datetime | None = None
    if "послезавтра" in low:
        base = now + timedelta(days=2)
    elif "завтра" in low:
        base = now + timedelta(days=1)
    elif "сегодня" in low:
        base = now

    if base is not None:
        return base.replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp()

    for fmt in (
        "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d.%m.%Y %H:%M", "%d.%m.%Y",
    ):
        try:
            return datetime.strptime(raw, fmt).timestamp()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw).timestamp()
    except ValueError:
        return 0.0


def day_bounds(when: str) -> tuple[float, float]:
    """Return (start_ts, end_ts) for today/tomorrow/day after."""
    now = datetime.now()
    low = when.lower().strip()
    if "послезавтра" in low:
        day = now + timedelta(days=2)
    elif "сегодня" in low:
        day = now
    else:
        day = now + timedelta(days=1)
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start.timestamp(), end.timestamp()


def fmt_ts(ts: float) -> str:
    if not ts:
        return "?"
    return datetime.fromtimestamp(ts).strftime("%d.%m %H:%M")
