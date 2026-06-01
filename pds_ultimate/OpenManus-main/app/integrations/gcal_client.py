"""Google Calendar client — direct API, no PDS autonomy store."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.integrations.datetime_ru import day_bounds, fmt_ts, parse_datetime
from app.integrations.env_config import TIMEZONE
from app.integrations.google_auth import build_google_service


class GCalClient:
    def __init__(self) -> None:
        self._svc = None
        self._reason = ""

    def _service(self):
        if self._svc is not None:
            return self._svc
        svc, reason = build_google_service("calendar", "v3")
        if not svc:
            self._reason = reason
            return None
        self._svc = svc
        return self._svc

    def available(self) -> tuple[bool, str]:
        return (self._service() is not None), self._reason

    def _list(self, t_min: datetime, t_max: datetime) -> list[dict]:
        svc = self._service()
        if not svc:
            return []
        resp = svc.events().list(
            calendarId="primary",
            timeMin=t_min.astimezone(timezone.utc).isoformat(),
            timeMax=t_max.astimezone(timezone.utc).isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=100,
        ).execute()
        out = []
        for ev in resp.get("items", []):
            start = ev.get("start", {})
            dt = start.get("dateTime") or start.get("date")
            if not dt:
                continue
            try:
                ts = datetime.fromisoformat(dt.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
            end_ts = ts + 3600
            end = ev.get("end", {})
            edt = end.get("dateTime") or end.get("date")
            if edt:
                try:
                    end_ts = datetime.fromisoformat(edt.replace("Z", "+00:00")).timestamp()
                except ValueError:
                    pass
            out.append({
                "gcal_id": ev.get("id", ""),
                "title": ev.get("summary", "(без названия)"),
                "start_at": ts,
                "end_at": end_ts,
            })
        return out

    async def list_events(self, days: int = 14) -> list[dict]:
        now = datetime.now(timezone.utc)
        return await asyncio.to_thread(
            self._list, now - timedelta(days=1), now + timedelta(days=days)
        )

    async def list_between(self, start_ts: float, end_ts: float) -> list[dict]:
        return await asyncio.to_thread(
            self._list,
            datetime.fromtimestamp(start_ts, tz=timezone.utc),
            datetime.fromtimestamp(end_ts, tz=timezone.utc),
        )

    async def add_event(
        self, title: str, start_at: float, *, end_at: float | None = None, notes: str = ""
    ) -> str:
        def _insert() -> str:
            svc = self._service()
            if not svc:
                return ""
            start = datetime.fromtimestamp(start_at)
            end = datetime.fromtimestamp(end_at) if end_at and end_at > start_at else start + timedelta(hours=1)
            body = {
                "summary": title,
                "description": notes,
                "start": {"dateTime": start.isoformat(), "timeZone": TIMEZONE},
                "end": {"dateTime": end.isoformat(), "timeZone": TIMEZONE},
            }
            ev = svc.events().insert(calendarId="primary", body=body).execute()
            return ev.get("id", "")

        return await asyncio.to_thread(_insert)

    async def delete_event(self, gcal_id: str) -> bool:
        def _delete() -> bool:
            svc = self._service()
            if not svc or not gcal_id:
                return False
            svc.events().delete(calendarId="primary", eventId=gcal_id).execute()
            return True

        return await asyncio.to_thread(_delete)

    async def clear_day(self, when: str) -> tuple[int, list[str]]:
        start, end = day_bounds(when)
        events = await self.list_between(start, end)
        deleted = []
        for ev in events:
            if ev.get("gcal_id") and await self.delete_event(ev["gcal_id"]):
                deleted.append(ev["title"])
        return len(deleted), deleted

    def find_conflicts(self, start_at: float, end_at: float, events: list[dict]) -> list[dict]:
        out = []
        for ev in events:
            s = ev.get("start_at") or 0
            e = ev.get("end_at") or (s + 3600)
            if start_at < e and end_at > s:
                out.append(ev)
        return out

    async def add_with_check(self, title: str, start_at: str, end_at: str = "", notes: str = "") -> str:
        ts = parse_datetime(start_at)
        if not ts:
            return f"ERROR: не понял время «{start_at}»"
        ts_end = parse_datetime(end_at) if end_at else ts + 3600
        if ts_end <= ts:
            ts_end = ts + 3600

        ok, reason = self.available()
        if not ok:
            return f"ERROR: Google Calendar: {reason}"

        nearby = await self.list_between(ts - 43200, ts + 43200)
        conflicts = self.find_conflicts(ts, ts_end, nearby)
        if conflicts:
            lines = [
                f"• {fmt_ts(c['start_at'])}–{fmt_ts(c['end_at'])} «{c['title']}»"
                for c in conflicts
            ]
            return "ERROR: время занято:\n" + "\n".join(lines)

        gid = await self.add_event(title, ts, end_at=ts_end, notes=notes)
        if not gid:
            return "ERROR: не удалось создать событие"
        return f"OK: «{title}» {fmt_ts(ts)} – {fmt_ts(ts_end)}"


gcal = GCalClient()
