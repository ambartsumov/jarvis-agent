"""Tests for the autonomy substrate: directives, schedule, recurrence, heartbeat."""

from __future__ import annotations

import time

import pytest

from pds_ultimate.core.autonomy.store import AutonomyStore, compute_next_run


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr("pds_ultimate.core.autonomy.store._DB_PATH", tmp_path / "auto.db")
    return AutonomyStore()


class TestRecurrence:
    def test_once_returns_zero(self):
        assert compute_next_run("once") == 0.0
        assert compute_next_run("") == 0.0

    def test_hourly(self):
        nxt = compute_next_run("hourly")
        assert 3500 < nxt - time.time() < 3700

    def test_interval(self):
        nxt = compute_next_run("interval:120")
        assert 110 < nxt - time.time() < 130

    def test_daily_in_future(self):
        assert compute_next_run("daily") > time.time()

    def test_weekly_in_future(self):
        assert compute_next_run("weekly:mon") > time.time()


class TestDirectives:
    def test_add_and_list(self, store):
        store.add_directive(1, "ping me", recurrence="hourly")
        items = store.list_directives(1)
        assert len(items) == 1 and items[0].text == "ping me"

    def test_passive_directive_not_due(self, store):
        store.add_directive(1, "always be polite")  # no recurrence/run_at
        assert store.due_directives() == []

    def test_due_directive_detected(self, store):
        store.add_directive(1, "run now", run_at=time.time() - 5)
        due = store.due_directives()
        assert len(due) == 1

    def test_mark_ran_reschedules_recurring(self, store):
        did = store.add_directive(1, "hourly task", recurrence="hourly", run_at=time.time() - 5)
        store.mark_directive_ran(did)
        assert store.due_directives() == []  # next_run pushed into future
        assert len(store.list_directives(1)) == 1  # still active

    def test_mark_ran_deactivates_once(self, store):
        did = store.add_directive(1, "one shot", run_at=time.time() - 5)
        store.mark_directive_ran(did)
        assert store.list_directives(1, active_only=True) == []

    def test_remove(self, store):
        did = store.add_directive(1, "x", recurrence="daily")
        assert store.remove_directive(1, did)
        assert store.list_directives(1) == []

    def test_isolation_per_owner(self, store):
        store.add_directive(1, "owner1")
        store.add_directive(2, "owner2")
        assert len(store.list_directives(1)) == 1
        assert len(store.list_directives(2)) == 1


class TestSchedule:
    def test_add_and_today(self, store):
        from datetime import datetime
        noon = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0).timestamp()
        store.add_event(1, "Lunch", start_at=noon)
        today = store.events_between(1, noon - 3600, noon + 3600)
        assert any(e.title == "Lunch" for e in today)

    def test_due_reminder(self, store):
        store.add_event(1, "Past", start_at=time.time() - 10, remind_at=time.time() - 10)
        due = store.due_reminders()
        assert len(due) == 1

    def test_reminder_delivered_marks_done(self, store):
        eid = store.add_event(1, "X", remind_at=time.time() - 10)
        store.mark_reminder_delivered(eid)
        assert store.due_reminders() == []

    def test_recurring_reminder_reschedules(self, store):
        eid = store.add_event(1, "Daily standup", start_at=time.time() - 10,
                              remind_at=time.time() - 10, recurrence="daily")
        store.mark_reminder_delivered(eid)
        # Recurring → not delivered, pushed to future
        assert store.due_reminders() == []
        assert len(store.list_events(1, upcoming_only=False)) == 1


@pytest.mark.asyncio
class TestHeartbeat:
    async def test_tick_delivers_reminder_and_runs_directive(self, store, monkeypatch):
        from pds_ultimate.core.autonomy.heartbeat import Heartbeat

        # Point the global store used by heartbeat at our temp store
        monkeypatch.setattr("pds_ultimate.core.autonomy.heartbeat.autonomy_store", store)

        store.add_event(777, "Meeting", start_at=time.time() - 10, remind_at=time.time() - 10)
        store.add_directive(777, "do the thing", run_at=time.time() - 5)

        sent: list[tuple[int, str]] = []

        async def notifier(cid, text):
            sent.append((cid, text))

        # Fake the agent so no real LLM call happens
        from pds_ultimate.core.agent.ethan import agent

        class _Resp:
            answer = "директива выполнена"

        async def fake_run(uid, text, **kw):
            return _Resp()

        monkeypatch.setattr(agent, "run", fake_run)

        hb = Heartbeat()
        hb.set_notifier(notifier)
        await hb.tick()

        joined = " ".join(t for _, t in sent)
        assert "Напоминание" in joined
        assert "директива выполнена" in joined
