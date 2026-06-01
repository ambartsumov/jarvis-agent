"""Google Calendar integration — two-way sync with the local schedule store."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from pds_ultimate.config import config, logger
from pds_ultimate.integrations.google_auth import build_google_service, get_google_credentials


class GoogleCalendarClient:
    def __init__(self) -> None:
        self._service = None
        self._reason = ""

    def _load_service(self):
        if self._service is not None:
            return self._service
        svc, reason = build_google_service("calendar", "v3")
        if not svc:
            self._reason = reason
            return None
        self._service = svc
        return self._service

    def available(self) -> tuple[bool, str]:
        svc = self._load_service()
        return (svc is not None), self._reason

    def _list(self, time_min: datetime, time_max: datetime) -> list[dict]:
        svc = self._load_service()
        if not svc:
            return []
        resp = svc.events().list(
            calendarId="primary",
            timeMin=time_min.astimezone(timezone.utc).isoformat(),
            timeMax=time_max.astimezone(timezone.utc).isoformat(),
            singleEvents=True, orderBy="startTime", maxResults=100,
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
            end_ts = 0.0
            end = ev.get("end", {})
            edt = end.get("dateTime") or end.get("date")
            if edt:
                try:
                    end_ts = datetime.fromisoformat(edt.replace("Z", "+00:00")).timestamp()
                except ValueError:
                    end_ts = 0.0
            out.append({
                "gcal_id": ev.get("id", ""),
                "title": ev.get("summary", "(без названия)"),
                "notes": ev.get("description", "") or "",
                "start_at": ts,
                "end_at": end_ts,
            })
        return out

    def _insert(
        self, title: str, start_at: float, notes: str = "",
        *, end_at: float | None = None, duration_min: int = 60,
    ) -> str:
        svc = self._load_service()
        if not svc:
            return ""
        tz_name = config.browser.timezone or "Asia/Ashgabat"
        start = datetime.fromtimestamp(start_at)
        if end_at and end_at > start_at:
            end = datetime.fromtimestamp(end_at)
        else:
            end = start + timedelta(minutes=duration_min)
        body = {
            "summary": title,
            "description": notes,
            "start": {"dateTime": start.isoformat(), "timeZone": tz_name},
            "end": {"dateTime": end.isoformat(), "timeZone": tz_name},
        }
        ev = svc.events().insert(calendarId="primary", body=body).execute()
        return ev.get("id", "")

    def _delete(self, gcal_id: str) -> bool:
        svc = self._load_service()
        if not svc or not gcal_id:
            return False
        svc.events().delete(calendarId="primary", eventId=gcal_id).execute()
        return True

    def _find_conflicts(self, start_at: float, end_at: float, events: list[dict]) -> list[dict]:
        """Return events overlapping [start_at, end_at)."""
        out: list[dict] = []
        for ev in events:
            s = ev.get("start_at") or 0
            e = ev.get("end_at") or (s + 3600)
            if start_at < e and end_at > s:
                out.append(ev)
        return out

    async def list_events(self, days: int = 30) -> list[dict]:
        now = datetime.now(timezone.utc)
        return await asyncio.to_thread(self._list, now - timedelta(days=1), now + timedelta(days=days))

    async def list_events_between(self, start_ts: float, end_ts: float) -> list[dict]:
        return await asyncio.to_thread(
            self._list,
            datetime.fromtimestamp(start_ts, tz=timezone.utc),
            datetime.fromtimestamp(end_ts, tz=timezone.utc),
        )

    async def add_event(
        self, title: str, start_at: float, notes: str = "",
        *, end_at: float | None = None, duration_min: int = 60,
    ) -> str:
        return await asyncio.to_thread(
            self._insert, title, start_at, notes,
            end_at=end_at, duration_min=duration_min,
        )

    async def delete_event(self, gcal_id: str) -> bool:
        return await asyncio.to_thread(self._delete, gcal_id)


gcal_client = GoogleCalendarClient()


async def two_way_sync(owner_id: int) -> dict:
    """Pull GCal→local and push local→GCal. Returns counts."""
    from pds_ultimate.core.autonomy.store import autonomy_store

    ok, reason = gcal_client.available()
    if not ok:
        hint = ""
        creds, _ = get_google_credentials()
        if not creds and config.gmail.api_key:
            hint = (
                " API key сохранён, но для Calendar нужен OAuth: "
                "python3 -m pds_ultimate.integrations.gmail_auth"
            )
        return {"ok": False, "reason": reason + hint, "pulled": 0, "pushed": 0}

    pulled = pushed = 0

    remote = await gcal_client.list_events(days=30)
    for ev in remote:
        if not ev["gcal_id"]:
            continue
        existing = autonomy_store.get_event_by_gcal_id(owner_id, ev["gcal_id"])
        if existing:
            continue
        eid = autonomy_store.add_event(
            owner_id, ev["title"], start_at=ev["start_at"], notes=ev["notes"],
        )
        autonomy_store.set_gcal_id(eid, ev["gcal_id"], source="gcal")
        pulled += 1

    import time as _time

    for e in autonomy_store.all_events(owner_id):
        if e.gcal_id or e.source == "gcal":
            continue
        if e.start_at and e.start_at < _time.time() - 86400:
            continue
        gid = await gcal_client.add_event(e.title, e.start_at or _time.time(), e.notes)
        if gid:
            autonomy_store.set_gcal_id(e.id, gid, source="local")
            pushed += 1

    logger.info(f"GCal sync: pulled={pulled}, pushed={pushed}")
    return {"ok": True, "reason": "", "pulled": pulled, "pushed": pushed}
