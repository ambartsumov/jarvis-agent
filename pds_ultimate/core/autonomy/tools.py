"""Agent-facing tools for directives & schedule. The agent drives these itself."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from pds_ultimate.core.autonomy.store import autonomy_store
from pds_ultimate.core.tools.base import ToolResult, ToolSpec
from pds_ultimate.core.tools.registry import tool_registry


def _parse_dt(value: str) -> float:
    """Parse human/ISO/Russian relative datetime → epoch. 0 on failure."""
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
        dt = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return dt.timestamp()

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


def _hour_24(h: int, context: str) -> int:
    """«2 часа дня» → 14, «2 утра» → 2. Без уточнения 1–7 → день (+12)."""
    if h >= 8:
        return h
    t = context.lower()
    if re.search(r"утр|ноч|am\b", t) and 1 <= h <= 11:
        return h
    if re.search(r"часов?\s+дня|дня|pm|вечер|после\s+обед", t) and 1 <= h <= 11:
        return h + 12
    if 1 <= h <= 7:
        return h + 12  # «с 2 до 4» без уточнения = дневное время
    return h


def _split_compound(message: str) -> tuple[str, str | None]:
    """Split «удали … и сделай …» → (create_part, clear_day_word)."""
    m = re.search(
        r"удали\s+все\s+на\s+(завтра|сегодня|послезавтра)(?:\s+и\s+(.+))?",
        message, re.I | re.S,
    )
    if m:
        clear_word = m.group(1).lower()
        tail = (m.group(2) or "").strip()
        if tail:
            tail = re.sub(r"^(?:сделай|запиши|добавь|поставь|создай)\s+", "", tail, flags=re.I)
            return tail, clear_word
        return "", clear_word
    if re.search(r"удали.*(?:все\s+)?событ|очисти.*календар", message, re.I):
        day_m = re.search(r"на\s+(завтра|сегодня|послезавтра)", message, re.I)
        clear_word = (day_m.group(1) if day_m else "завтра").lower()
        rest = re.sub(r"удали.*?(?:событ|календар).*?(?:и|,\s*)?", "", message, count=1, flags=re.I)
        rest = re.sub(r"^(?:сделай|запиши|добавь|поставь|создай)\s+", "", rest.strip(), flags=re.I)
        return rest, clear_word
    return message, None


def _detect_day(text: str, default: str = "завтра") -> str:
    t = text.lower()
    if "послезавтра" in t:
        return "послезавтра"
    if "сегодня" in t:
        return "сегодня"
    if "завтра" in t:
        return "завтра"
    return default


def _strip_calendar_noise(text: str) -> str:
    cleaned = re.sub(
        r"с\s+\d{1,2}(?:[:.]\d{2})?\s+до\s+\d{1,2}(?:[:.]\d{2})?(?:\s+(?:часов?\s+дня|утра|вечера))?",
        " ", text, flags=re.I,
    )
    cleaned = re.sub(r"в\s+\d{1,2}(?:[:.]\d{2})?\s+часов?", " ", cleaned, flags=re.I)
    for pat in (
        r"(?:завтра|сегодня|послезавтра)",
        r"^(?:сделай|запиши|добавь|поставь|создай)\s+",
        r"запиши\s*(?:это|в\s+календар[ье])?",
        r"создай\s*(?:событие|встречу)?",
        r"отправ\w*\s*(?:эме?il|письм\w*).*",
        r"[\w.+-]+@[\w.-]+\.\w+",
        r"у меня\s+",
        r"напиши\s+",
        r"часов?\s+дня",
        r"^ладно\s+",
    ):
        cleaned = re.sub(pat, " ", cleaned, flags=re.I)
    return re.sub(r"\s+", " ", cleaned).strip(" .,-")


def _extract_event_title(create_text: str) -> str:
    """Pull event title from the create clause (any event)."""
    m = re.search(
        r"событие\s*:\s*(.+?)(?:\.|$|,\s*(?:завтра|сегодня)|\s+(?:завтра|сегодня|с\s+\d|в\s+\d))",
        create_text, re.I,
    )
    if m:
        cand = m.group(1).strip(" .,")
        if cand and len(cand) > 1:
            return cand[:80]

    m = re.search(r"встреча\s+(.+?)(?:\.|$|,\s*(?:завтра|сегодня)|\s+с\s+\d|\s+в\s+\d)", create_text, re.I)
    if m:
        cand = m.group(1).strip(" .,")
        if cand and len(cand) > 1:
            return f"Встреча {cand}"[:80]

    m = re.search(
        r"у меня (?:будет\s+)?(.+?)(?:\.|$|,\s*отправ|\s+и\s+отправ|\s+запиши)",
        create_text, re.I,
    )
    if m:
        cand = _strip_calendar_noise(m.group(1))
        if cand and len(cand) > 1:
            return cand[:80]

    cand = _strip_calendar_noise(create_text)
    if cand and len(cand) > 1:
        return cand[:80]
    return "Событие"


def _norm_title(s: str) -> str:
    return re.sub(r"[^\w\s]", "", s.lower()).strip()


def titles_similar(a: str, b: str) -> bool:
    na, nb = _norm_title(a), _norm_title(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


def parse_calendar_request(message: str) -> dict:
    """Extract calendar fields from natural language."""
    create_text, clear_day_word = _split_compound(message)
    clear_day = clear_day_word is not None
    src = create_text if create_text.strip() else message
    t = src.lower()
    day_word = _detect_day(src)
    title = _extract_event_title(src) if create_text.strip() or not clear_day else ""

    start_h, start_m, end_h, end_m = None, 0, None, 0

    tm = re.search(
        r"с\s+(\d{1,2})(?:[:.](\d{2}))?\s+до\s+(\d{1,2})(?:[:.](\d{2}))?",
        t,
    )
    if tm:
        start_h = _hour_24(int(tm.group(1)), src)
        start_m = int(tm.group(2) or 0)
        end_h = _hour_24(int(tm.group(3)), src)
        end_m = int(tm.group(4) or 0)
    else:
        at_m = re.search(r"в\s+(\d{1,2})(?:[:.](\d{2}))?\s+часов?", t)
        if at_m:
            start_h = _hour_24(int(at_m.group(1)), src)
            start_m = int(at_m.group(2) or 0)
            end_h = min(start_h + 1, 23)
            end_m = start_m

    if start_h is None:
        start_h, end_h = 14, 16

    start_at = f"{day_word} {start_h}:{start_m:02d}"
    end_at = f"{day_word} {end_h}:{end_m:02d}"

    return {
        "title": title,
        "start_at": start_at,
        "end_at": end_at,
        "notes": "",
        "clear_day": clear_day,
        "clear_day_word": clear_day_word or "завтра",
        "day_word": day_word,
        "create_only": bool(create_text.strip() or not clear_day),
    }


def _fmt(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "—"


# ─── Directives ───────────────────────────────────────────────────────────────
async def _directive_add(
    user_id: int, text: str, recurrence: str = "", run_at: str = "",
    trigger: str = "", channel: str = "",
) -> ToolResult:
    did = autonomy_store.add_directive(
        user_id, text, recurrence=recurrence, run_at=_parse_dt(run_at),
        trigger=trigger, channel=channel,
    )
    if trigger:
        ch = channel or "любой канал"
        return ToolResult(success=True, output=f"Триггер-директива #{did} активна ({ch}, условие: «{trigger}»): {text}")
    d = autonomy_store.list_directives(user_id)
    nxt = next((x.next_run for x in d if x.id == did), 0)
    when = f", след. запуск {_fmt(nxt)}" if nxt else " (контекстная)"
    return ToolResult(success=True, output=f"Директива #{did} сохранена{when}: {text}")


async def _directive_list(user_id: int) -> ToolResult:
    items = autonomy_store.list_directives(user_id)
    if not items:
        return ToolResult(success=True, output="Активных директив нет.")
    lines = [
        f"#{d.id} [{d.recurrence or 'once/passive'}] след={_fmt(d.next_run)} — {d.text}"
        for d in items
    ]
    return ToolResult(success=True, output="\n".join(lines))


async def _directive_remove(user_id: int, directive_id: int) -> ToolResult:
    ok = autonomy_store.remove_directive(user_id, int(directive_id))
    return ToolResult(success=ok, output=f"Директива #{directive_id} удалена" if ok else "", error="" if ok else "Не найдена")


# ─── Schedule ──────────────────────────────────────────────────────────────────
async def _schedule_add(
    user_id: int, title: str, start_at: str, remind_at: str = "", notes: str = "", recurrence: str = "",
) -> ToolResult:
    start = _parse_dt(start_at)
    if not start:
        return ToolResult(success=False, output="", error=f"Не удалось разобрать дату: {start_at}")
    eid = autonomy_store.add_event(
        user_id, title, start_at=start, remind_at=_parse_dt(remind_at), notes=notes, recurrence=recurrence,
    )
    return ToolResult(success=True, output=f"Событие #{eid} «{title}» на {_fmt(start)} добавлено.")


async def _schedule_list(user_id: int) -> ToolResult:
    items = autonomy_store.list_events(user_id)
    if not items:
        return ToolResult(success=True, output="Расписание пусто.")
    lines = [f"#{e.id} {_fmt(e.start_at)} — {e.title}" + (f" ({e.notes})" if e.notes else "") for e in items]
    return ToolResult(success=True, output="\n".join(lines))


async def _schedule_today(user_id: int) -> ToolResult:
    now = datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    end = start + 86400
    items = autonomy_store.events_between(user_id, start, end)
    if not items:
        return ToolResult(success=True, output="На сегодня событий нет.")
    lines = [f"{_fmt(e.start_at)} — {e.title}" for e in items]
    return ToolResult(success=True, output="Сегодня:\n" + "\n".join(lines))


async def _schedule_remove(user_id: int, event_id: int) -> ToolResult:
    ok = autonomy_store.remove_event(user_id, int(event_id))
    return ToolResult(success=ok, output=f"Событие #{event_id} удалено" if ok else "", error="" if ok else "Не найдено")


# ─── Google Calendar ──────────────────────────────────────────────────────────
async def _gcal_sync(user_id: int) -> ToolResult:
    from pds_ultimate.integrations.gcal import two_way_sync

    res = await two_way_sync(user_id)
    if not res["ok"]:
        return ToolResult(success=False, output="", error=f"Google Calendar не готов: {res['reason']}")
    return ToolResult(success=True, output=f"Синхронизация: импортировано {res['pulled']}, выгружено {res['pushed']}.")


async def _gcal_list(user_id: int, days: int = 14) -> ToolResult:
    from pds_ultimate.integrations.gcal import gcal_client

    ok, reason = gcal_client.available()
    if not ok:
        return ToolResult(success=False, output="", error=f"Google Calendar не готов: {reason}")
    events = await gcal_client.list_events(days=days)
    if not events:
        return ToolResult(success=True, output="В Google Calendar нет ближайших событий.")
    lines = [f"{_fmt(e['start_at'])} — {e['title']}" for e in events]
    return ToolResult(success=True, output="\n".join(lines))


def _day_bounds(day_word: str) -> tuple[float, float]:
    """Return (start_of_day, end_of_day) timestamps for завтра/сегодня."""
    now = datetime.now()
    if day_word == "завтра":
        base = now + timedelta(days=1)
    elif day_word == "сегодня":
        base = now
    else:
        base = now + timedelta(days=1)
    start = base.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start.timestamp(), end.timestamp()


async def _gcal_clear_day(user_id: int, when: str = "завтра") -> ToolResult:
    from pds_ultimate.integrations.gcal import gcal_client

    ok, reason = gcal_client.available()
    if not ok:
        return ToolResult(success=False, output="", error=f"Google Calendar не готов: {reason}")

    day_word = "завтра" if "завтра" in when.lower() else ("сегодня" if "сегодня" in when.lower() else when)
    t0, t1 = _day_bounds(day_word)
    events = await gcal_client.list_events_between(t0, t1)
    removed = 0
    for ev in events:
        if ev.get("gcal_id") and await gcal_client.delete_event(ev["gcal_id"]):
            removed += 1
    return ToolResult(success=True, output=f"Удалено событий на {day_word}: {removed}.")


async def _gcal_add(
    user_id: int, title: str, start_at: str, notes: str = "", end_at: str = "",
) -> ToolResult:
    from pds_ultimate.integrations.gcal import gcal_client

    ts = _parse_dt(start_at)
    if not ts:
        return ToolResult(success=False, output="", error=f"Не удалось разобрать дату начала: {start_at}")
    ts_end = _parse_dt(end_at) if end_at else 0.0
    if not ts_end or ts_end <= ts:
        ts_end = ts + 2 * 3600  # default 2h if end missing

    ok, reason = gcal_client.available()
    if not ok:
        return ToolResult(success=False, output="", error=f"Google Calendar не готов: {reason}")

    # Conflict check — warn and refuse (don't silently overlap)
    day0, day1 = ts - 43200, ts + 43200
    nearby = await gcal_client.list_events_between(day0, day1)
    conflicts = gcal_client._find_conflicts(ts, ts_end, nearby)
    if conflicts:
        if all(titles_similar(title, c["title"]) for c in conflicts):
            c = conflicts[0]
            end_ts = c.get("end_at") or c["start_at"] + 3600
            return ToolResult(
                success=True,
                output=(
                    f"✅ Уже в календаре: {_fmt(c['start_at'])}–{_fmt(end_ts)} «{c['title']}»."
                ),
            )
        lines = [
            f"• {_fmt(c['start_at'])}–{_fmt(c['end_at'] or c['start_at']+3600)} «{c['title']}»"
            for c in conflicts
        ]
        return ToolResult(
            success=False, output="",
            error=(
                f"⛔ На это время уже занято:\n" + "\n".join(lines) +
                f"\n\nТвоё: «{title}» {_fmt(ts)}–{_fmt(ts_end)}. "
                "Скажи «удали все на …» или выбери другое время."
            ),
        )

    gid = await gcal_client.add_event(title, ts, notes, end_at=ts_end)
    eid = autonomy_store.add_event(user_id, title, start_at=ts, notes=notes)
    if gid:
        autonomy_store.set_gcal_id(eid, gid, source="local")
    return ToolResult(
        success=True,
        output=f"✅ «{title}» в Google Calendar: {_fmt(ts)} – {_fmt(ts_end)}.",
    )


AUTONOMY_TOOL_NAMES = {
    "directive_add", "directive_list", "directive_remove",
    "schedule_add", "schedule_list", "schedule_today", "schedule_remove",
    "gcal_sync", "gcal_list", "gcal_add", "gcal_clear_day",
}


def register_autonomy_tools() -> int:
    tools = [
        ToolSpec(
            name="directive_add",
            description=(
                "Сохранить ПОСТОЯННОЕ распоряжение, которое ты будешь исполнять сам автономно. "
                "text — что делать (на естественном языке, любая задача). "
                "ДВА типа: \n"
                "1) По расписанию: recurrence='daily'|'hourly'|'weekly:mon'|'interval:3600'|'once', "
                "run_at=ISO-время первого запуска. \n"
                "2) ПО ТРИГГЕРУ (реакция на входящие в реальном времени): задай trigger — условие "
                "на естественном языке (напр. 'сообщения от мамы', 'про оплату', 'любое'), и "
                "channel='telegram'|'whatsapp'|'any'. Тогда при входящем сообщении ты сам сработаешь. \n"
                "Без recurrence/run_at/trigger — пассивное правило (контекст)."
            ),
            parameters={"type": "object", "properties": {
                "user_id": {"type": "integer"},
                "text": {"type": "string"},
                "recurrence": {"type": "string"},
                "run_at": {"type": "string", "description": "ISO datetime, напр. 2026-06-01 08:00"},
                "trigger": {"type": "string", "description": "Условие срабатывания на входящие (естественный язык)"},
                "channel": {"type": "string", "description": "telegram|whatsapp|any"},
            }, "required": ["user_id", "text"]},
            handler=_directive_add, category="autonomy", risk="medium",
        ),
        ToolSpec(
            name="directive_list", description="Показать все активные директивы.",
            parameters={"type": "object", "properties": {"user_id": {"type": "integer"}}, "required": ["user_id"]},
            handler=_directive_list, category="autonomy", risk="low",
        ),
        ToolSpec(
            name="directive_remove", description="Удалить/отменить директиву по id.",
            parameters={"type": "object", "properties": {
                "user_id": {"type": "integer"}, "directive_id": {"type": "integer"}},
                "required": ["user_id", "directive_id"]},
            handler=_directive_remove, category="autonomy", risk="medium",
        ),
        ToolSpec(
            name="schedule_add",
            description="Добавить событие/встречу в расписание владельца (с напоминанием).",
            parameters={"type": "object", "properties": {
                "user_id": {"type": "integer"},
                "title": {"type": "string"},
                "start_at": {"type": "string", "description": "ISO datetime начала"},
                "remind_at": {"type": "string", "description": "ISO datetime напоминания (необязательно)"},
                "notes": {"type": "string"},
                "recurrence": {"type": "string", "description": "daily|weekly:mon|interval:N|''"},
            }, "required": ["user_id", "title", "start_at"]},
            handler=_schedule_add, category="autonomy", risk="medium",
        ),
        ToolSpec(
            name="schedule_list", description="Показать предстоящие события расписания.",
            parameters={"type": "object", "properties": {"user_id": {"type": "integer"}}, "required": ["user_id"]},
            handler=_schedule_list, category="autonomy", risk="low",
        ),
        ToolSpec(
            name="schedule_today", description="Что запланировано на сегодня.",
            parameters={"type": "object", "properties": {"user_id": {"type": "integer"}}, "required": ["user_id"]},
            handler=_schedule_today, category="autonomy", risk="low",
        ),
        ToolSpec(
            name="schedule_remove", description="Удалить событие по id.",
            parameters={"type": "object", "properties": {
                "user_id": {"type": "integer"}, "event_id": {"type": "integer"}},
                "required": ["user_id", "event_id"]},
            handler=_schedule_remove, category="autonomy", risk="medium",
        ),
        ToolSpec(
            name="gcal_sync", description="Двусторонняя синхронизация расписания с Google Calendar.",
            parameters={"type": "object", "properties": {"user_id": {"type": "integer"}}, "required": ["user_id"]},
            handler=_gcal_sync, category="autonomy", risk="medium",
        ),
        ToolSpec(
            name="gcal_list", description="Показать события из Google Calendar.",
            parameters={"type": "object", "properties": {
                "user_id": {"type": "integer"}, "days": {"type": "integer"}}, "required": ["user_id"]},
            handler=_gcal_list, category="autonomy", risk="low",
        ),
        ToolSpec(
            name="gcal_add",
            description=(
                "Добавить событие в Google Calendar. Ты сам вытаскиваешь title/время из речи владельца. "
                "start_at и end_at — на русском («сегодня 18:00», «завтра 14:00»). end_at обязателен для диапазона. "
                "Проверяет конфликты — если время занято, вернёт ошибку (не создаёт дубликат)."
            ),
            parameters={"type": "object", "properties": {
                "user_id": {"type": "integer"}, "title": {"type": "string"},
                "start_at": {"type": "string", "description": "Начало, напр. завтра 14:00"},
                "end_at": {"type": "string", "description": "Конец, напр. завтра 16:00"},
                "notes": {"type": "string"}}, "required": ["user_id", "title", "start_at"]},
            handler=_gcal_add, category="autonomy", risk="medium",
        ),
        ToolSpec(
            name="gcal_clear_day",
            description="Удалить ВСЕ события Google Calendar на день (завтра/сегодня).",
            parameters={"type": "object", "properties": {
                "user_id": {"type": "integer"},
                "when": {"type": "string", "description": "завтра | сегодня | ISO date"},
            }, "required": ["user_id"]},
            handler=_gcal_clear_day, category="autonomy", risk="high",
        ),
    ]
    for spec in tools:
        tool_registry.register(spec)
    return len(tools)
