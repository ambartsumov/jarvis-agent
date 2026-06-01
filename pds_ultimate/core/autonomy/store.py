"""Autonomy substrate — persistent directives & schedule.

This is the revolutionary core: the user expresses behavior in natural language
("каждое утро присылай погоду", "напомни о встрече в пятницу"), the agent stores it
here, and the heartbeat executes it autonomously. NO behavior is hardcoded — directives
are just natural-language tasks the agent runs on a schedule it computes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Boolean, Float, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from pds_ultimate.config import DATA_DIR, logger

_DB_PATH = DATA_DIR / "autonomy.db"


class _Base(DeclarativeBase):
    pass


class Directive(_Base):
    """A standing natural-language instruction the agent executes autonomously."""
    __tablename__ = "directives"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    text: Mapped[str] = mapped_column(Text)
    # "" / "once" / "hourly" / "daily" / "weekly:mon" / "interval:SECONDS"
    recurrence: Mapped[str] = mapped_column(String(64), default="")
    next_run: Mapped[float] = mapped_column(Float, default=0.0)  # epoch; 0 = passive/contextual
    last_run: Mapped[float] = mapped_column(Float, default=0.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[float] = mapped_column(Float, default=lambda: time.time())
    # Trigger directives: react to incoming messages in real time (not by timer)
    trigger: Mapped[str] = mapped_column(Text, default="")  # natural-language condition
    channel: Mapped[str] = mapped_column(String(32), default="")  # telegram|whatsapp|any|""


class ScheduleEvent(_Base):
    """A calendar event / reminder the agent manages for the owner."""
    __tablename__ = "schedule_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(Text)
    notes: Mapped[str] = mapped_column(Text, default="")
    start_at: Mapped[float] = mapped_column(Float, default=0.0)   # event time
    remind_at: Mapped[float] = mapped_column(Float, default=0.0)  # when to notify
    recurrence: Mapped[str] = mapped_column(String(64), default="")
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[float] = mapped_column(Float, default=lambda: time.time())
    # Google Calendar two-way sync mapping
    gcal_id: Mapped[str] = mapped_column(String(256), default="")
    source: Mapped[str] = mapped_column(String(32), default="local")  # local|gcal


# ─── Recurrence helpers (generic, not behavior-specific) ──────────────────────
_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def compute_next_run(recurrence: str, after: float | None = None, hour: int = 9, minute: int = 0) -> float:
    """Compute the next epoch timestamp for a recurrence spec. 0 = no further runs."""
    now = datetime.fromtimestamp(after or time.time())
    rec = (recurrence or "").strip().lower()

    if rec in ("", "once"):
        return 0.0
    if rec == "hourly":
        return (now + timedelta(hours=1)).timestamp()
    if rec == "daily":
        nxt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        return nxt.timestamp()
    if rec.startswith("interval:"):
        try:
            secs = max(30, int(rec.split(":", 1)[1]))
        except ValueError:
            secs = 3600
        return now.timestamp() + secs
    if rec.startswith("weekly:"):
        dow = _WEEKDAYS.get(rec.split(":", 1)[1][:3], 0)
        nxt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        days_ahead = (dow - now.weekday()) % 7
        if days_ahead == 0 and nxt <= now:
            days_ahead = 7
        return (nxt + timedelta(days=days_ahead)).timestamp()
    return 0.0


@dataclass
class AutonomyStore:
    def __post_init__(self) -> None:
        self.engine = create_engine(f"sqlite:///{_DB_PATH}", future=True)
        _Base.metadata.create_all(self.engine)
        self._migrate()
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)

    def _migrate(self) -> None:
        """Add new columns to existing DBs without data loss."""
        import sqlite3

        conn = sqlite3.connect(str(_DB_PATH))
        cur = conn.cursor()
        migrations = {
            "directives": [("trigger", "TEXT DEFAULT ''"), ("channel", "VARCHAR(32) DEFAULT ''")],
            "schedule_events": [("gcal_id", "VARCHAR(256) DEFAULT ''"), ("source", "VARCHAR(32) DEFAULT 'local'")],
        }
        for table, cols in migrations.items():
            try:
                cur.execute(f"PRAGMA table_info({table})")
                existing = {row[1] for row in cur.fetchall()}
                for col, ddl in cols:
                    if col not in existing:
                        cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
            except sqlite3.OperationalError:
                pass
        conn.commit()
        conn.close()

    # ─── Directives ──────────────────────────────────────────────────────────
    def add_directive(
        self, owner_id: int, text: str, *, recurrence: str = "", run_at: float = 0.0,
        trigger: str = "", channel: str = "",
    ) -> int:
        next_run = run_at
        if not next_run and recurrence and not trigger:
            next_run = compute_next_run(recurrence)
        with self.session_factory() as s:
            d = Directive(
                owner_id=owner_id, text=text, recurrence=recurrence, next_run=next_run,
                trigger=trigger, channel=channel,
            )
            s.add(d)
            s.commit()
            s.refresh(d)
            return d.id

    def trigger_directives(self, owner_id: int, channel: str = "") -> list[Directive]:
        """Active directives that react to incoming messages on a channel."""
        with self.session_factory() as s:
            stmt = select(Directive).where(
                Directive.owner_id == owner_id,
                Directive.active.is_(True),
                Directive.trigger != "",
            )
            items = list(s.scalars(stmt).all())
        if channel:
            items = [d for d in items if d.channel in ("", "any", channel)]
        return items

    def list_directives(self, owner_id: int, *, active_only: bool = True) -> list[Directive]:
        with self.session_factory() as s:
            stmt = select(Directive).where(Directive.owner_id == owner_id)
            if active_only:
                stmt = stmt.where(Directive.active.is_(True))
            return list(s.scalars(stmt.order_by(Directive.created_at.desc())).all())

    def remove_directive(self, owner_id: int, directive_id: int) -> bool:
        with self.session_factory() as s:
            d = s.get(Directive, directive_id)
            if not d or d.owner_id != owner_id:
                return False
            s.delete(d)
            s.commit()
            return True

    def due_directives(self, now: float | None = None) -> list[Directive]:
        now = now or time.time()
        with self.session_factory() as s:
            stmt = select(Directive).where(
                Directive.active.is_(True), Directive.next_run > 0, Directive.next_run <= now
            )
            return list(s.scalars(stmt).all())

    def mark_directive_ran(self, directive_id: int) -> None:
        with self.session_factory() as s:
            d = s.get(Directive, directive_id)
            if not d:
                return
            d.last_run = time.time()
            nxt = compute_next_run(d.recurrence, after=d.last_run)
            if nxt > 0:
                d.next_run = nxt
            else:
                d.active = False  # one-shot done
            s.commit()

    # ─── Schedule events ─────────────────────────────────────────────────────
    def add_event(
        self, owner_id: int, title: str, *, start_at: float = 0.0, remind_at: float = 0.0,
        notes: str = "", recurrence: str = "",
    ) -> int:
        if not remind_at and start_at:
            remind_at = start_at
        with self.session_factory() as s:
            e = ScheduleEvent(
                owner_id=owner_id, title=title, notes=notes, start_at=start_at,
                remind_at=remind_at, recurrence=recurrence,
            )
            s.add(e)
            s.commit()
            s.refresh(e)
            return e.id

    def list_events(self, owner_id: int, *, upcoming_only: bool = True) -> list[ScheduleEvent]:
        with self.session_factory() as s:
            stmt = select(ScheduleEvent).where(ScheduleEvent.owner_id == owner_id)
            if upcoming_only:
                stmt = stmt.where(ScheduleEvent.start_at >= time.time() - 86400)
            return list(s.scalars(stmt.order_by(ScheduleEvent.start_at.asc())).all())

    def events_between(self, owner_id: int, start: float, end: float) -> list[ScheduleEvent]:
        with self.session_factory() as s:
            stmt = select(ScheduleEvent).where(
                ScheduleEvent.owner_id == owner_id,
                ScheduleEvent.start_at >= start,
                ScheduleEvent.start_at < end,
            )
            return list(s.scalars(stmt.order_by(ScheduleEvent.start_at.asc())).all())

    def remove_event(self, owner_id: int, event_id: int) -> bool:
        with self.session_factory() as s:
            e = s.get(ScheduleEvent, event_id)
            if not e or e.owner_id != owner_id:
                return False
            s.delete(e)
            s.commit()
            return True

    def get_event_by_gcal_id(self, owner_id: int, gcal_id: str) -> ScheduleEvent | None:
        with self.session_factory() as s:
            return s.scalar(
                select(ScheduleEvent).where(
                    ScheduleEvent.owner_id == owner_id, ScheduleEvent.gcal_id == gcal_id
                )
            )

    def set_gcal_id(self, event_id: int, gcal_id: str, *, source: str = "local") -> None:
        with self.session_factory() as s:
            e = s.get(ScheduleEvent, event_id)
            if e:
                e.gcal_id = gcal_id
                e.source = source
                s.commit()

    def all_events(self, owner_id: int) -> list[ScheduleEvent]:
        with self.session_factory() as s:
            return list(s.scalars(
                select(ScheduleEvent).where(ScheduleEvent.owner_id == owner_id)
            ).all())

    def due_reminders(self, now: float | None = None) -> list[ScheduleEvent]:
        now = now or time.time()
        with self.session_factory() as s:
            stmt = select(ScheduleEvent).where(
                ScheduleEvent.delivered.is_(False),
                ScheduleEvent.remind_at > 0,
                ScheduleEvent.remind_at <= now,
            )
            return list(s.scalars(stmt).all())

    def mark_reminder_delivered(self, event_id: int) -> None:
        with self.session_factory() as s:
            e = s.get(ScheduleEvent, event_id)
            if not e:
                return
            if e.recurrence:
                nxt = compute_next_run(e.recurrence, after=e.remind_at)
                if nxt > 0:
                    delta = nxt - e.remind_at
                    e.remind_at = nxt
                    e.start_at = e.start_at + delta if e.start_at else nxt
                    s.commit()
                    return
            e.delivered = True
            s.commit()


autonomy_store = AutonomyStore()
