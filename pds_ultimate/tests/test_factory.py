"""Tests for the dynamic tool factory (self-built tools, Manus-style)."""

from __future__ import annotations

import pytest

from pds_ultimate.core.tools.factory import create_dynamic_tool, register_factory_tool
from pds_ultimate.core.tools.registry import tool_registry


@pytest.mark.asyncio
class TestToolFactory:
    async def test_create_and_execute_sync(self):
        r = await create_dynamic_tool(
            "mul_test", "multiply",
            {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}},
            "async def run(a, b):\n    return a * b",
            persist=False,
        )
        assert r.success
        res = await tool_registry.execute("mul_test", {"a": 3, "b": 4})
        assert res.success and "12" in res.output

    async def test_create_with_httpx_available(self):
        r = await create_dynamic_tool(
            "uses_httpx", "checks namespace",
            {"type": "object", "properties": {}},
            "async def run(**kw):\n    return 'httpx ok' if httpx else 'no'",
            persist=False,
        )
        assert r.success
        res = await tool_registry.execute("uses_httpx", {})
        assert "httpx ok" in res.output

    async def test_invalid_name_rejected(self):
        r = await create_dynamic_tool("123 bad-name!", "x", {}, "async def run():\n    return 1", persist=False)
        assert not r.success

    async def test_missing_run_function(self):
        r = await create_dynamic_tool("no_run", "x", {}, "x = 5", persist=False)
        assert not r.success and "run" in r.error.lower()

    async def test_runtime_error_captured(self):
        await create_dynamic_tool("boom", "x", {}, "async def run():\n    raise ValueError('boom')", persist=False)
        res = await tool_registry.execute("boom", {})
        assert not res.success and "boom" in res.error

    async def test_factory_tool_registered(self):
        register_factory_tool()
        assert tool_registry.get("create_tool") is not None
        assert tool_registry.get("create_tool").risk == "high"


class TestChannelRegistration:
    def test_channel_tools_register(self):
        from pds_ultimate.core.tools.channels import register_channel_tools

        n = register_channel_tools()
        assert n == 7
        for name in ("telegram_send", "whatsapp_send", "email_send", "email_read"):
            assert tool_registry.get(name) is not None

    def test_channel_send_tools_are_high_risk(self):
        from pds_ultimate.core.tools.channels import register_channel_tools

        register_channel_tools()
        assert tool_registry.get("telegram_send").risk == "high"
        assert tool_registry.get("email_send").risk == "high"
