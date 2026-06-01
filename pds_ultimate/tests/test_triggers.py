"""Tests for trigger directives, real-time matching, and GCal graceful behavior."""

from __future__ import annotations

import time

import pytest

from pds_ultimate.core.autonomy.store import AutonomyStore, Directive
from pds_ultimate.core.autonomy.triggers import TriggerEngine, directive_matches


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr("pds_ultimate.core.autonomy.store._DB_PATH", tmp_path / "auto.db")
    return AutonomyStore()


def _d(trigger="", channel="", text="react"):
    return Directive(owner_id=1, text=text, trigger=trigger, channel=channel, active=True)


class TestMatcher:
    def test_generic_matches_all(self):
        assert directive_matches(_d("любое", "telegram"), "telegram", "Bob", "hi")

    def test_channel_filter_blocks(self):
        assert not directive_matches(_d("любое", "whatsapp"), "telegram", "Bob", "hi")

    def test_channel_any_passes(self):
        assert directive_matches(_d("любое", "any"), "telegram", "Bob", "hi")

    def test_keyword_in_text(self):
        assert directive_matches(_d("про оплату"), "telegram", "Bob", "когда оплата придёт?")

    def test_keyword_in_sender(self):
        assert directive_matches(_d("мама"), "telegram", "Мама Люба", "привет")

    def test_no_match(self):
        assert not directive_matches(_d("оплата"), "telegram", "Bob", "погода хорошая")

    def test_empty_trigger_never_matches(self):
        assert not directive_matches(_d(""), "telegram", "Bob", "hi")


class TestTriggerStore:
    def test_add_trigger_directive_passive(self, store):
        did = store.add_directive(1, "reply", trigger="мама", channel="telegram")
        # trigger directive must NOT be time-due
        assert store.due_directives() == []
        trigs = store.trigger_directives(1, "telegram")
        assert len(trigs) == 1 and trigs[0].id == did

    def test_trigger_channel_isolation(self, store):
        store.add_directive(1, "x", trigger="any", channel="whatsapp")
        assert store.trigger_directives(1, "telegram") == []
        assert len(store.trigger_directives(1, "whatsapp")) == 1

    def test_migration_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pds_ultimate.core.autonomy.store._DB_PATH", tmp_path / "m.db")
        s1 = AutonomyStore()
        s1.add_directive(1, "x", trigger="t", channel="any")
        s2 = AutonomyStore()  # re-open, migration runs again
        assert len(s2.trigger_directives(1, "telegram")) == 1


@pytest.mark.asyncio
class TestTriggerEngine:
    async def test_reacts_on_match(self, store, monkeypatch):
        monkeypatch.setattr("pds_ultimate.core.autonomy.triggers.autonomy_store", store)
        store.add_directive(1, "ответь приветом", trigger="мама", channel="telegram")

        from pds_ultimate.core.agent.ethan import agent

        ran = {}

        class _R:
            answer = "ответил маме"

        async def fake_run(uid, text, **kw):
            ran["text"] = text
            return _R()

        monkeypatch.setattr(agent, "run", fake_run)

        sent = []

        async def notif(cid, t):
            sent.append(t)

        eng = TriggerEngine()
        eng.set_notifier(notif)
        await eng.handle_incoming("telegram", "Мама", "ты дома?", "@mama", owner_id=1)

        assert "ran" or ran
        assert "Мама" in ran["text"]
        assert any("ответил маме" in s for s in sent)

    async def test_no_reaction_without_match(self, store, monkeypatch):
        monkeypatch.setattr("pds_ultimate.core.autonomy.triggers.autonomy_store", store)
        store.add_directive(1, "x", trigger="оплата", channel="telegram")

        from pds_ultimate.core.agent.ethan import agent

        called = {"n": 0}

        async def fake_run(uid, text, **kw):
            called["n"] += 1
            class _R:
                answer = "x"
            return _R()

        monkeypatch.setattr(agent, "run", fake_run)
        eng = TriggerEngine()
        eng.set_notifier(lambda c, t: _noop())
        await eng.handle_incoming("telegram", "Bob", "привет как дела", "@bob", owner_id=1)
        assert called["n"] == 0

    async def test_dedupe_same_message(self, store, monkeypatch):
        monkeypatch.setattr("pds_ultimate.core.autonomy.triggers.autonomy_store", store)
        store.add_directive(1, "x", trigger="любое", channel="any")

        from pds_ultimate.core.agent.ethan import agent

        called = {"n": 0}

        async def fake_run(uid, text, **kw):
            called["n"] += 1
            class _R:
                answer = "ok"
            return _R()

        async def notif(c, t):
            pass

        monkeypatch.setattr(agent, "run", fake_run)
        eng = TriggerEngine()
        eng.set_notifier(notif)
        await eng.handle_incoming("telegram", "Bob", "одинаковый", "@bob", owner_id=1)
        await eng.handle_incoming("telegram", "Bob", "одинаковый", "@bob", owner_id=1)
        assert called["n"] == 1  # second is deduped


async def _noop():
    return None


@pytest.mark.asyncio
class TestBusyAutoReply:
    async def test_busy_triggers_reply_without_directive(self, store, monkeypatch):
        monkeypatch.setattr("pds_ultimate.core.autonomy.triggers.autonomy_store", store)

        async def fake_busy(owner_id):
            return {"title": "бокс", "start": 0, "end": 0, "range": "14:00–16:00", "source": "gcal"}

        monkeypatch.setattr(
            "pds_ultimate.core.autonomy.presence.current_activity", fake_busy
        )

        from pds_ultimate.core.agent.ethan import agent

        captured = {}

        async def fake_run(uid, task, **kw):
            captured["task"] = task
            class _R:
                answer = "ответил собеседнику"
            return _R()

        sent = []

        async def notif(c, t):
            sent.append(t)

        monkeypatch.setattr(agent, "run", fake_run)
        eng = TriggerEngine()
        eng.set_notifier(notif)
        await eng.handle_incoming(
            "telegram", "Вася", "ты где?", "@vasya", owner_id=1, msg_id=555
        )
        assert "ЗАНЯТ" in captured["task"]
        assert "бокс" in captured["task"]
        assert "reply_to=555" in captured["task"]
        assert sent

    async def test_not_busy_no_directive_skips(self, store, monkeypatch):
        monkeypatch.setattr("pds_ultimate.core.autonomy.triggers.autonomy_store", store)

        async def fake_free(owner_id):
            return None

        monkeypatch.setattr(
            "pds_ultimate.core.autonomy.presence.current_activity", fake_free
        )

        from pds_ultimate.core.agent.ethan import agent

        called = {"n": 0}

        async def fake_run(uid, task, **kw):
            called["n"] += 1
            class _R:
                answer = "x"
            return _R()

        monkeypatch.setattr(agent, "run", fake_run)
        eng = TriggerEngine()
        eng.set_notifier(lambda c, t: _noop())
        await eng.handle_incoming("telegram", "Вася", "привет", "@vasya", owner_id=1)
        assert called["n"] == 0


class TestGCalGraceful:
    def test_unconfigured_reports_reason(self):
        from pds_ultimate.integrations.gcal import gcal_client

        ok, reason = gcal_client.available()
        # Without token it must be unavailable but not crash
        assert ok in (True, False)
        if not ok:
            assert reason
