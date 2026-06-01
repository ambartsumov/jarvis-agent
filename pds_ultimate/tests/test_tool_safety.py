"""
Tests for Tool Safety System (Step 7)
=======================================
Tests:
- ToolAuditLogger: logging, stats, rate limiting, queries
- ParameterValidator: type checks, coercion, limits, enum
- ToolBlocklist: block/unblock, reasons
- ToolSandbox: sandboxed execution, error boundaries, timeout
- sanitize_params: sensitive key redaction
- Integration with ToolRegistry: audit + rate limits in execute()
"""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from pds_ultimate.core.tool_audit import (
    AuditEntry,
    AuditEventType,
    ToolAuditLogger,
    ToolRateLimiter,
    sanitize_params,
    tool_audit,
)
from pds_ultimate.core.tool_sandbox import (
    MAX_PARAM_ARRAY_LEN,
    MAX_PARAM_STRING_LEN,
    ExecutionRecord,
    ParameterValidator,
    ParamValidationError,
    SideEffect,
    SideEffectType,
    ToolBlocklist,
    ToolSandbox,
    tool_sandbox,
)
from pds_ultimate.core.tools import Tool, ToolParameter, ToolRegistry, ToolResult

# ═══════════════════════════════════════════════════════════════════════════════
# 1. sanitize_params
# ═══════════════════════════════════════════════════════════════════════════════


class TestSanitizeParams:
    def test_empty_params(self):
        assert sanitize_params(None) == "(no params)"
        assert sanitize_params({}) == "(no params)"

    def test_normal_params(self):
        result = sanitize_params({"query": "hello", "limit": 10})
        assert "hello" in result
        assert "10" in result

    def test_redacts_password(self):
        result = sanitize_params({"password": "secret123"})
        assert "secret123" not in result
        assert "REDACTED" in result

    def test_redacts_api_key(self):
        result = sanitize_params({"api_key": "sk-xxx", "query": "hello"})
        assert "sk-xxx" not in result
        assert "hello" in result

    def test_redacts_token(self):
        result = sanitize_params({"access_token": "abc123"})
        assert "abc123" not in result

    def test_truncates_long_string(self):
        long_val = "x" * 500
        result = sanitize_params({"data": long_val})
        assert len(result) < 1000
        assert "…" in result

    def test_case_insensitive_redaction(self):
        result = sanitize_params({"API_KEY": "secret", "Password": "pwd"})
        assert "secret" not in result
        assert "pwd" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ToolRateLimiter
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolRateLimiter:
    def test_allows_within_limit(self):
        rl = ToolRateLimiter()
        rl.set_limit("test_tool", 5)
        for _ in range(5):
            assert rl.check("test_tool") is True
            rl.record("test_tool")

    def test_blocks_over_limit(self):
        rl = ToolRateLimiter()
        rl.set_limit("test_tool", 3)
        for _ in range(3):
            rl.record("test_tool")
        assert rl.check("test_tool") is False

    def test_default_limit(self):
        rl = ToolRateLimiter()
        # Default is 30
        for _ in range(29):
            rl.record("any_tool")
        assert rl.check("any_tool") is True
        rl.record("any_tool")
        assert rl.check("any_tool") is False

    def test_get_usage(self):
        rl = ToolRateLimiter()
        rl.set_limit("t1", 10)
        for _ in range(3):
            rl.record("t1")
        usage = rl.get_usage("t1")
        assert usage["current"] == 3
        assert usage["limit"] == 10
        assert usage["remaining"] == 7

    def test_reset_specific(self):
        rl = ToolRateLimiter()
        rl.record("t1")
        rl.record("t2")
        rl.reset("t1")
        usage_t1 = rl.get_usage("t1")
        usage_t2 = rl.get_usage("t2")
        assert usage_t1["current"] == 0
        assert usage_t2["current"] == 1

    def test_reset_all(self):
        rl = ToolRateLimiter()
        rl.record("t1")
        rl.record("t2")
        rl.reset()
        assert rl.get_usage("t1")["current"] == 0
        assert rl.get_usage("t2")["current"] == 0

    def test_independent_tools(self):
        rl = ToolRateLimiter()
        rl.set_limit("t1", 2)
        rl.set_limit("t2", 2)
        rl.record("t1")
        rl.record("t1")
        assert rl.check("t1") is False
        assert rl.check("t2") is True


# ═══════════════════════════════════════════════════════════════════════════════
# 3. ToolAuditLogger
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolAuditLogger:
    def test_log_start(self):
        al = ToolAuditLogger()
        entry = al.log_start("test_tool", {"q": "hello"})
        assert entry.event_type == AuditEventType.TOOL_CALL_START
        assert entry.tool_name == "test_tool"
        assert "hello" in entry.params_preview

    def test_log_success(self):
        al = ToolAuditLogger()
        entry = al.log_success("test_tool", "result data", 150)
        assert entry.event_type == AuditEventType.TOOL_CALL_SUCCESS
        assert entry.duration_ms == 150
        assert "result" in entry.output_preview

    def test_log_failure(self):
        al = ToolAuditLogger()
        entry = al.log_failure("test_tool", "Connection refused", 200)
        assert entry.event_type == AuditEventType.TOOL_CALL_FAILURE
        assert "Connection" in entry.error

    def test_log_blocked(self):
        al = ToolAuditLogger()
        entry = al.log_blocked("dangerous_tool", "Rate limit exceeded")
        assert entry.event_type == AuditEventType.TOOL_CALL_BLOCKED

    def test_stats_tracking(self):
        al = ToolAuditLogger()
        al.log_success("t1", "ok", 100)
        al.log_success("t1", "ok", 200)
        al.log_failure("t1", "err", 50)

        stats = al.get_tool_stats("t1")
        assert stats["total_calls"] == 3
        assert stats["successes"] == 2
        assert stats["failures"] == 1
        assert stats["avg_duration_ms"] == 117  # (100+200+50)/3
        assert stats["max_duration_ms"] == 200
        assert stats["min_duration_ms"] == 50
        assert stats["error_rate"] == 33.3

    def test_get_recent(self):
        al = ToolAuditLogger()
        for i in range(10):
            al.log_success(f"t{i}", "ok", 10)
        recent = al.get_recent(5)
        assert len(recent) == 5

    def test_get_by_tool(self):
        al = ToolAuditLogger()
        al.log_success("t1", "ok", 10)
        al.log_success("t2", "ok", 10)
        al.log_success("t1", "ok", 10)

        entries = al.get_by_tool("t1")
        assert len(entries) == 2
        assert all(e.tool_name == "t1" for e in entries)

    def test_get_failures(self):
        al = ToolAuditLogger()
        al.log_success("t1", "ok", 10)
        al.log_failure("t2", "err", 10)
        al.log_blocked("t3", "blocked")

        failures = al.get_failures()
        assert len(failures) == 2
        assert all(
            e.event_type in (
                AuditEventType.TOOL_CALL_FAILURE,
                AuditEventType.TOOL_CALL_BLOCKED,
            )
            for e in failures
        )

    def test_summary(self):
        al = ToolAuditLogger()
        al.log_success("t1", "ok", 10)
        al.log_failure("t2", "err", 10)

        summary = al.summary
        assert summary["total_calls"] == 2
        assert summary["total_errors"] == 1
        assert summary["tools_used"] == 2

    def test_bounded_buffer(self):
        al = ToolAuditLogger(max_entries=10)
        for i in range(20):
            al.log_success(f"t{i}", "ok", 10)
        assert al.total_entries == 10

    def test_clear(self):
        al = ToolAuditLogger()
        al.log_success("t1", "ok", 10)
        al.clear()
        assert al.total_entries == 0
        assert al.summary["total_calls"] == 0

    def test_rate_limit_integration(self):
        al = ToolAuditLogger()
        al.rate_limiter.set_limit("t1", 2)
        assert al.check_rate_limit("t1") is True
        al.log_start("t1", {})
        al.log_start("t1", {})
        assert al.check_rate_limit("t1") is False

    def test_audit_entry_to_dict(self):
        entry = AuditEntry(
            event_type=AuditEventType.TOOL_CALL_SUCCESS,
            tool_name="test",
            timestamp=time.time(),
            output_preview="result data",
            duration_ms=100,
        )
        d = entry.to_dict()
        assert d["event"] == "tool_call_success"
        assert d["tool"] == "test"
        assert d["duration_ms"] == 100


# ═══════════════════════════════════════════════════════════════════════════════
# 4. ParameterValidator
# ═══════════════════════════════════════════════════════════════════════════════

class TestParameterValidator:
    def test_valid_params(self):
        schema = [
            ToolParameter("name", "string", "User name", required=True),
            ToolParameter("age", "number", "User age",
                          required=False, default=0),
        ]
        result = ParameterValidator.validate({"name": "Alice"}, schema)
        assert result["name"] == "Alice"
        assert result["age"] == 0  # default

    def test_missing_required(self):
        schema = [
            ToolParameter("name", "string", "Name", required=True),
        ]
        with pytest.raises(ParamValidationError, match="Missing required"):
            ParameterValidator.validate({}, schema)

    def test_type_check_string(self):
        schema = [ToolParameter("q", "string", "Query")]
        result = ParameterValidator.validate({"q": "hello"}, schema)
        assert result["q"] == "hello"

    def test_type_coercion_number(self):
        schema = [ToolParameter("count", "number", "Count")]
        result = ParameterValidator.validate({"count": "42"}, schema)
        assert result["count"] == 42.0

    def test_type_coercion_boolean(self):
        schema = [ToolParameter("flag", "boolean", "Flag")]
        result = ParameterValidator.validate({"flag": "true"}, schema)
        assert result["flag"] is True

    def test_type_coercion_boolean_russian(self):
        schema = [ToolParameter("flag", "boolean", "Flag")]
        result = ParameterValidator.validate({"flag": "да"}, schema)
        assert result["flag"] is True

    def test_string_too_long(self):
        schema = [ToolParameter("data", "string", "Data")]
        long_val = "x" * (MAX_PARAM_STRING_LEN + 1)
        with pytest.raises(ParamValidationError, match="string too long"):
            ParameterValidator.validate({"data": long_val}, schema)

    def test_array_too_long(self):
        schema = [ToolParameter("items", "array", "Items")]
        long_arr = list(range(MAX_PARAM_ARRAY_LEN + 1))
        with pytest.raises(ParamValidationError, match="array too long"):
            ParameterValidator.validate({"items": long_arr}, schema)

    def test_enum_check_pass(self):
        schema = [
            ToolParameter("color", "string", "Color",
                          enum=["red", "blue", "green"]),
        ]
        result = ParameterValidator.validate({"color": "red"}, schema)
        assert result["color"] == "red"

    def test_enum_check_fail(self):
        schema = [
            ToolParameter("color", "string", "Color", enum=["red", "blue"]),
        ]
        with pytest.raises(ParamValidationError, match="not in allowed"):
            ParameterValidator.validate({"color": "purple"}, schema)

    def test_strict_mode_rejects_unexpected(self):
        schema = [ToolParameter("q", "string", "Query")]
        with pytest.raises(ParamValidationError, match="Unexpected"):
            ParameterValidator.validate(
                {"q": "hello", "extra": "bad"}, schema, strict=True,
            )

    def test_non_strict_allows_extra(self):
        schema = [ToolParameter("q", "string", "Query")]
        result = ParameterValidator.validate(
            {"q": "hello", "extra": "ok"}, schema, strict=False,
        )
        assert result["extra"] == "ok"

    def test_wrong_type_no_coercion(self):
        schema = [ToolParameter("items", "array", "Items")]
        with pytest.raises(ParamValidationError, match="expected array"):
            ParameterValidator.validate({"items": "not_array"}, schema)

    def test_empty_schema(self):
        result = ParameterValidator.validate({"any": "thing"}, [])
        assert result == {"any": "thing"}

    def test_default_value_used(self):
        schema = [
            ToolParameter("limit", "number", "Limit",
                          required=False, default=10),
        ]
        result = ParameterValidator.validate({}, schema)
        assert result["limit"] == 10


# ═══════════════════════════════════════════════════════════════════════════════
# 5. ToolBlocklist
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolBlocklist:
    def test_initially_empty(self):
        bl = ToolBlocklist()
        assert bl.is_blocked("any_tool") is False
        assert len(bl.blocked_tools) == 0

    def test_block_tool(self):
        bl = ToolBlocklist()
        bl.block("dangerous_tool", "Security risk")
        assert bl.is_blocked("dangerous_tool") is True
        assert bl.get_reason("dangerous_tool") == "Security risk"

    def test_unblock_tool(self):
        bl = ToolBlocklist()
        bl.block("tool1", "temp")
        bl.unblock("tool1")
        assert bl.is_blocked("tool1") is False

    def test_unblock_nonexistent(self):
        bl = ToolBlocklist()
        bl.unblock("nonexistent")  # should not raise

    def test_blocked_tools_frozenset(self):
        bl = ToolBlocklist()
        bl.block("t1")
        bl.block("t2")
        frozen = bl.blocked_tools
        assert isinstance(frozen, frozenset)
        assert "t1" in frozen
        assert "t2" in frozen

    def test_clear(self):
        bl = ToolBlocklist()
        bl.block("t1")
        bl.block("t2")
        bl.clear()
        assert len(bl.blocked_tools) == 0

    def test_independent_tools(self):
        bl = ToolBlocklist()
        bl.block("t1")
        assert bl.is_blocked("t1") is True
        assert bl.is_blocked("t2") is False


# ═══════════════════════════════════════════════════════════════════════════════
# 6. ExecutionRecord
# ═══════════════════════════════════════════════════════════════════════════════

class TestExecutionRecord:
    def test_duration_calculation(self):
        r = ExecutionRecord(
            tool_name="test", params={},
            started_at=100.0, completed_at=100.5,
        )
        assert r.duration_ms == 500

    def test_no_side_effects(self):
        r = ExecutionRecord(
            tool_name="test", params={}, started_at=0,
        )
        assert r.has_side_effects is False

    def test_with_side_effects(self):
        r = ExecutionRecord(
            tool_name="test", params={}, started_at=0,
            side_effects=[
                SideEffect(SideEffectType.FILE_CREATED, "created test.txt"),
            ],
        )
        assert r.has_side_effects is True


# ═══════════════════════════════════════════════════════════════════════════════
# 7. ToolSandbox
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolSandbox:
    def _make_tool(self, name="test_tool", handler=None, timeout=5.0, params=None):
        return Tool(
            name=name,
            description="Test tool",
            parameters=params or [],
            handler=handler,
            timeout=timeout,
        )

    @pytest.mark.asyncio
    async def test_successful_execution(self):
        sandbox = ToolSandbox()

        async def handler(query=""):
            return {"result": f"Found: {query}"}

        tool = self._make_tool(handler=handler)
        record = await sandbox.run(tool, {"query": "test"})
        assert record.success is True
        assert "Found: test" in record.output

    @pytest.mark.asyncio
    async def test_blocked_tool(self):
        sandbox = ToolSandbox()
        sandbox.blocklist.block("bad_tool", "Security risk")

        tool = self._make_tool(name="bad_tool", handler=AsyncMock())
        record = await sandbox.run(tool)
        assert record.success is False
        assert "blocked" in record.error.lower()

    @pytest.mark.asyncio
    async def test_no_handler(self):
        sandbox = ToolSandbox()
        tool = self._make_tool(handler=None)
        record = await sandbox.run(tool)
        assert record.success is False
        assert "no handler" in record.error.lower()

    @pytest.mark.asyncio
    async def test_timeout(self):
        sandbox = ToolSandbox()

        async def slow():
            await asyncio.sleep(10)

        tool = self._make_tool(handler=slow, timeout=0.1)
        record = await sandbox.run(tool, timeout=0.1)
        assert record.success is False
        assert "timeout" in record.error.lower()

    @pytest.mark.asyncio
    async def test_exception_handled(self):
        sandbox = ToolSandbox()

        async def broken():
            raise RuntimeError("crash!")

        tool = self._make_tool(handler=broken)
        record = await sandbox.run(tool)
        assert record.success is False
        assert "RuntimeError" in record.error

    @pytest.mark.asyncio
    async def test_param_validation_fail(self):
        sandbox = ToolSandbox()
        params_schema = [
            ToolParameter("name", "string", "Name", required=True),
        ]
        tool = self._make_tool(handler=AsyncMock(), params=params_schema)
        record = await sandbox.run(tool, params={}, validate=True)
        assert record.success is False
        assert "validation" in record.error.lower()

    @pytest.mark.asyncio
    async def test_param_validation_pass(self):
        sandbox = ToolSandbox()
        params_schema = [
            ToolParameter("name", "string", "Name", required=True),
        ]

        async def handler(name=""):
            return f"Hello {name}"

        tool = self._make_tool(handler=handler, params=params_schema)
        record = await sandbox.run(tool, params={"name": "Alice"}, validate=True)
        assert record.success is True
        assert "Alice" in record.output

    @pytest.mark.asyncio
    async def test_history_recorded(self):
        sandbox = ToolSandbox()

        async def handler():
            return "ok"

        tool = self._make_tool(handler=handler)
        await sandbox.run(tool)
        await sandbox.run(tool)

        history = sandbox.get_history()
        assert len(history) == 2

    @pytest.mark.asyncio
    async def test_history_filtered_by_tool(self):
        sandbox = ToolSandbox()

        async def handler():
            return "ok"

        t1 = self._make_tool(name="tool_a", handler=handler)
        t2 = self._make_tool(name="tool_b", handler=handler)
        await sandbox.run(t1)
        await sandbox.run(t2)
        await sandbox.run(t1)

        history_a = sandbox.get_history("tool_a")
        assert len(history_a) == 2

    @pytest.mark.asyncio
    async def test_stats(self):
        sandbox = ToolSandbox()

        async def handler():
            return "ok"

        async def broken():
            raise RuntimeError("fail")

        t1 = self._make_tool(name="t1", handler=handler)
        t2 = self._make_tool(name="t2", handler=broken)
        await sandbox.run(t1)
        await sandbox.run(t2)

        stats = sandbox.stats
        assert stats["total_executions"] == 2
        assert stats["successes"] == 1
        assert stats["failures"] == 1

    @pytest.mark.asyncio
    async def test_clear_history(self):
        sandbox = ToolSandbox()

        async def handler():
            return "ok"

        tool = self._make_tool(handler=handler)
        await sandbox.run(tool)
        sandbox.clear_history()
        assert len(sandbox.get_history()) == 0

    @pytest.mark.asyncio
    async def test_none_result(self):
        sandbox = ToolSandbox()

        async def handler():
            return None

        tool = self._make_tool(handler=handler)
        record = await sandbox.run(tool)
        assert record.success is True
        assert "успешно" in record.output.lower() or record.output

    @pytest.mark.asyncio
    async def test_dict_result(self):
        sandbox = ToolSandbox()

        async def handler():
            return {"key": "value"}

        tool = self._make_tool(handler=handler)
        record = await sandbox.run(tool)
        assert record.success is True
        assert "key" in record.output


# ═══════════════════════════════════════════════════════════════════════════════
# 8. ToolRegistry Integration with Audit
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolRegistryAudit:
    @pytest.mark.asyncio
    async def test_execute_logs_audit_success(self):
        registry = ToolRegistry()
        audit = ToolAuditLogger()

        async def handler(query=""):
            return ToolResult(
                tool_name="search", success=True, output="Found results",
            )

        tool = Tool(
            name="search", description="Search",
            handler=handler, parameters=[],
        )
        registry.register(tool)

        with patch("pds_ultimate.core.tool_audit.tool_audit", audit):
            result = await registry.execute("search", {"query": "test"})

        assert result.success is True
        assert audit.total_entries >= 2  # start + success

    @pytest.mark.asyncio
    async def test_execute_logs_audit_failure(self):
        registry = ToolRegistry()
        audit = ToolAuditLogger()

        async def handler():
            raise ValueError("bad input")

        tool = Tool(name="crash", description="Crash", handler=handler)
        registry.register(tool)

        with patch("pds_ultimate.core.tool_audit.tool_audit", audit):
            result = await registry.execute("crash")

        assert result.success is False
        failures = audit.get_failures()
        assert len(failures) >= 1

    @pytest.mark.asyncio
    async def test_execute_not_found_logs_audit(self):
        registry = ToolRegistry()
        audit = ToolAuditLogger()

        with patch("pds_ultimate.core.tool_audit.tool_audit", audit):
            result = await registry.execute("nonexistent")

        assert result.success is False
        assert audit.total_entries >= 1

    @pytest.mark.asyncio
    async def test_execute_rate_limited(self):
        registry = ToolRegistry()
        audit = ToolAuditLogger()
        audit.rate_limiter.set_limit("fast_tool", 2)

        async def handler():
            return "ok"

        tool = Tool(name="fast_tool", description="Fast", handler=handler)
        registry.register(tool)

        with patch("pds_ultimate.core.tool_audit.tool_audit", audit):
            # First 2 should succeed
            r1 = await registry.execute("fast_tool")
            r2 = await registry.execute("fast_tool")
            # Third should be rate limited
            r3 = await registry.execute("fast_tool")

        assert r1.success is True
        assert r2.success is True
        assert r3.success is False
        assert "лимит" in r3.error

    @pytest.mark.asyncio
    async def test_execute_kwargs_merged(self):
        """kwargs should be merged into params dict."""
        registry = ToolRegistry()
        audit = ToolAuditLogger()

        received = {}

        async def handler(**kw):
            received.update(kw)
            return "ok"

        tool = Tool(name="t1", description="T1", handler=handler)
        registry.register(tool)

        with patch("pds_ultimate.core.tool_audit.tool_audit", audit):
            await registry.execute("t1", query="hello", limit=10)

        assert received["query"] == "hello"
        assert received["limit"] == 10


# ═══════════════════════════════════════════════════════════════════════════════
# 9. SideEffect
# ═══════════════════════════════════════════════════════════════════════════════

class TestSideEffect:
    def test_creation(self):
        se = SideEffect(
            effect_type=SideEffectType.FILE_CREATED,
            description="Created report.pdf",
            reversible=True,
            rollback_info={"path": "/tmp/report.pdf"},
        )
        assert se.effect_type == SideEffectType.FILE_CREATED
        assert se.reversible is True
        assert se.rollback_info["path"] == "/tmp/report.pdf"

    def test_timestamp_auto(self):
        se = SideEffect(SideEffectType.API_CALL, "Called API")
        assert se.timestamp > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Global Instances
# ═══════════════════════════════════════════════════════════════════════════════

class TestGlobalInstances:
    def test_tool_audit_is_singleton(self):
        assert isinstance(tool_audit, ToolAuditLogger)

    def test_tool_sandbox_is_singleton(self):
        assert isinstance(tool_sandbox, ToolSandbox)

    def test_sandbox_has_blocklist(self):
        assert hasattr(tool_sandbox, "blocklist")

    def test_sandbox_has_validator(self):
        assert hasattr(tool_sandbox, "validator")

    def test_audit_has_rate_limiter(self):
        assert hasattr(tool_audit, "rate_limiter")
