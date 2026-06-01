"""Tests for agent core: LLM client parsing, routing, tool-call handling."""

from __future__ import annotations

import pytest

from pds_ultimate.core.agent.control import CancellationRegistry
from pds_ultimate.core.agent.ethan import EthanAgent
from pds_ultimate.core.llm.client import LLMClient, LLMResponse
from pds_ultimate.core.llm.router import ModelRouter, TaskKind


class TestLLMResponse:
    def test_total_tokens(self):
        r = LLMResponse(content="hi", prompt_tokens=10, completion_tokens=5)
        assert r.total_tokens == 15

    def test_defaults(self):
        r = LLMResponse(content="x")
        assert r.tool_calls == [] and r.finish_reason == "stop"


class TestJsonParsing:
    def test_plain_json(self):
        assert LLMClient._parse_json('{"a": 1}') == {"a": 1}

    def test_fenced_json(self):
        assert LLMClient._parse_json('```json\n{"a": 2}\n```') == {"a": 2}

    def test_embedded_json(self):
        assert LLMClient._parse_json('blah {"a": 3} trailing') == {"a": 3}


class TestModelRouter:
    def test_step_uses_fast_model(self):
        r = ModelRouter()
        _, _, model = r.select(TaskKind.STEP)
        assert model == r._ds.fast_model

    def test_plan_uses_reasoner(self):
        r = ModelRouter()
        _, _, model = r.select(TaskKind.PLAN)
        assert model == r._ds.model


class TestArgParsing:
    def test_dict_passthrough(self):
        assert EthanAgent._parse_args({"x": 1}) == {"x": 1}

    def test_json_string(self):
        assert EthanAgent._parse_args('{"x": 2}') == {"x": 2}

    def test_garbage_returns_empty(self):
        assert EthanAgent._parse_args("not json") == {}

    def test_none_returns_empty(self):
        assert EthanAgent._parse_args(None) == {}


class TestUserIdInjection:
    def test_injects_for_memory_tools(self):
        assert EthanAgent._inject_user_id("remember", {"fact": "x"}, 42)["user_id"] == 42
        assert EthanAgent._inject_user_id("recall", {}, 7)["user_id"] == 7

    def test_no_injection_for_other_tools(self):
        assert "user_id" not in EthanAgent._inject_user_id("read_file", {"path": "x"}, 42)


class TestCancellation:
    def test_cancel_flow(self):
        reg = CancellationRegistry()
        reg.begin(1)
        assert not reg.is_cancelled(1)
        assert reg.cancel(1)
        assert reg.is_cancelled(1)
        reg.end(1)
        assert not reg.is_cancelled(1)

    def test_cancel_unknown(self):
        reg = CancellationRegistry()
        assert not reg.cancel(999)


@pytest.mark.asyncio
class TestAgentLoop:
    """End-to-end native tool-calling loop with a mocked LLM."""

    async def test_tool_call_then_finish(self, monkeypatch):
        from pds_ultimate.core.llm.client import LLMResponse
        from pds_ultimate.core.tools.builtin import register_builtin_tools
        from pds_ultimate.config import config

        register_builtin_tools()
        a = EthanAgent()

        calls = {"n": 0}

        async def fake_complete(messages, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return LLMResponse(
                    content="",
                    tool_calls=[{
                        "id": "c1",
                        "function": {"name": "list_dir", "arguments": '{"path": "."}'},
                    }],
                    prompt_tokens=10, completion_tokens=5,
                )
            return LLMResponse(content="Готово, вот результат.", prompt_tokens=5, completion_tokens=3)

        async def fake_verify(q, ans, obs):
            return True, ans

        from pds_ultimate.core.agent import ethan as ethan_mod
        monkeypatch.setattr(ethan_mod.llm_client, "complete", fake_complete)
        monkeypatch.setattr(a.verifier, "verify", fake_verify)

        # owner runs as YOLO so list_dir (low risk) is allowed regardless
        resp = await a.run(config.telegram.owner_id, "покажи файлы")
        assert "Готово" in resp.answer
        assert "list_dir" in resp.tools_used
        assert calls["n"] == 2

    async def test_wall_clock_timeout(self, monkeypatch):
        import asyncio
        import time as _time
        from pds_ultimate.config import config

        a = EthanAgent()

        async def fake_verify(q, ans, obs):
            return True, ans

        monkeypatch.setattr(a.verifier, "verify", fake_verify)

        # Deadline already in the past → loop must bail out immediately
        resp = await a._run_inner(
            config.telegram.owner_id, "бесконечная задача", "", None,
            deadline=_time.monotonic() - 1, cancel_event=asyncio.Event(),
        )
        assert "лимит времени" in resp.answer.lower()

    async def test_cancellation_stops_loop(self, monkeypatch):
        import asyncio
        import time as _time
        from pds_ultimate.config import config

        a = EthanAgent()

        async def fake_verify(q, ans, obs):
            return True, ans

        monkeypatch.setattr(a.verifier, "verify", fake_verify)

        ev = asyncio.Event()
        ev.set()  # pre-cancelled
        resp = await a._run_inner(
            config.telegram.owner_id, "стоп", "", None,
            deadline=_time.monotonic() + 100, cancel_event=ev,
        )
        assert "остановлено" in resp.answer.lower()


@pytest.mark.asyncio
class TestGuardedExecute:
    async def test_unknown_tool(self):
        import asyncio
        a = EthanAgent()
        res = await a._guarded_execute("does_not_exist", {}, 1, asyncio.Event())
        assert not res.success and "Unknown tool" in res.error

    async def test_permission_denied_for_stranger(self):
        import asyncio
        from pds_ultimate.core.tools.builtin import register_builtin_tools
        register_builtin_tools()
        a = EthanAgent()
        res = await a._guarded_execute("shell_execute", {"command": "ls"}, 123456789, asyncio.Event())
        assert not res.success and "запрещ" in res.error.lower()
