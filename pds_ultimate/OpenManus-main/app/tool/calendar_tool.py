"""Google Calendar tool — direct GCal API (Manus orchestration)."""

from __future__ import annotations

from app.integrations.datetime_ru import fmt_ts, parse_datetime
from app.integrations.gcal_client import gcal
from app.tool.base import BaseTool, ToolResult

_CAL_DESC = """Google Calendar for the owner. Parse times yourself (сегодня/завтра 14:00).
Never create calendar events as text files — use this tool.

Actions:
- list: show upcoming events (days=14)
- add: create event (title, start_at, end_at optional, notes optional)
- clear_day: delete ALL events on a day (when=сегодня|завтра|послезавтра)
- check: verify OAuth is ready
"""


class CalendarTool(BaseTool):
    name: str = "calendar"
    description: str = _CAL_DESC
    parameters: dict = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "add", "clear_day", "check"]},
            "title": {"type": "string"},
            "start_at": {"type": "string", "description": "e.g. завтра 14:00"},
            "end_at": {"type": "string", "description": "e.g. завтра 16:00"},
            "when": {"type": "string", "description": "Day for clear_day: сегодня|завтра"},
            "notes": {"type": "string"},
            "days": {"type": "integer", "default": 14},
        },
        "required": ["action"],
    }

    async def execute(self, action: str, **kwargs) -> ToolResult:
        action = action.lower().strip()

        if action == "check":
            ok, reason = gcal.available()
            return self.success_response("OK: Google Calendar ready") if ok else self.fail_response(reason)

        if action == "list":
            days = int(kwargs.get("days") or 14)
            events = await gcal.list_events(days=days)
            if not events:
                return self.success_response("OK: no upcoming events")
            lines = [
                f"• {fmt_ts(e['start_at'])}–{fmt_ts(e['end_at'])} «{e['title']}»"
                for e in events[:30]
            ]
            return self.success_response("\n".join(lines))

        if action == "clear_day":
            when = kwargs.get("when") or "завтра"
            n, titles = await gcal.clear_day(when)
            return self.success_response(f"OK: deleted {n} events on {when}: {', '.join(titles) or '—'}")

        if action == "add":
            title = (kwargs.get("title") or "").strip()
            start_at = (kwargs.get("start_at") or "").strip()
            if not title or not start_at:
                return self.fail_response("title and start_at required")
            result = await gcal.add_with_check(
                title, start_at,
                end_at=kwargs.get("end_at") or "",
                notes=kwargs.get("notes") or "",
            )
            if result.startswith("ERROR"):
                return self.fail_response(result[6:].strip())
            return self.success_response(result)

        return self.fail_response(f"unknown action: {action}")
