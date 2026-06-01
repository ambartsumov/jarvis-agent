"""
Part 12 Tests — Production Hardening
======================================
Тесты для RateLimiter, RequestTracker, HealthChecker,
GracefulShutdown, ErrorReporter, StructuredLogger,
UptimeMonitor, SystemMetrics, AlertManager, ProductionHardening.
"""

from __future__ import annotations

import asyncio
import time
import unittest

from pds_ultimate.core.production import (
    Alert,
    AlertManager,
    AlertSeverity,
    ErrorEntry,
    ErrorReporter,
    GracefulShutdown,
    HealthChecker,
    HealthStatus,
    LogEntry,
    ProductionHardening,
    RateLimitEntry,
    RateLimiter,
    RateLimitResult,
    RequestRecord,
    RequestTracker,
    ShutdownPhase,
    ShutdownTask,
    StructuredLogger,
    SubsystemHealth,
    SystemMetrics,
    UptimeMonitor,
    production,
)

# ═══════════════════════════════════════════════════════════════════════════════
# RATE LIMITER
# ═══════════════════════════════════════════════════════════════════════════════


class TestRateLimitEntry(unittest.TestCase):

    def test_create_entry(self):
        e = RateLimitEntry(key="test", window_seconds=60, max_requests=5)
        assert e.key == "test"
        assert e.max_requests == 5
        assert e.remaining == 5

    def test_check_allowed(self):
        e = RateLimitEntry(key="k", window_seconds=60, max_requests=3)
        assert e.check() == RateLimitResult.ALLOWED

    def test_check_limited(self):
        e = RateLimitEntry(key="k", window_seconds=60, max_requests=2)
        now = time.time()
        e.record(now)
        e.record(now + 0.1)
        assert e.check(now + 0.2) == RateLimitResult.LIMITED
        assert e.total_limited == 1

    def test_check_blocked(self):
        e = RateLimitEntry(key="k", window_seconds=60, max_requests=10)
        now = time.time()
        e.block(300, now)
        assert e.check(now + 1) == RateLimitResult.BLOCKED
        # After block expires
        assert e.check(now + 301) == RateLimitResult.ALLOWED

    def test_cleanup_old(self):
        e = RateLimitEntry(key="k", window_seconds=10, max_requests=2)
        now = time.time()
        e.record(now - 20)  # Old
        e.record(now - 15)  # Old
        assert e.check(now) == RateLimitResult.ALLOWED

    def test_remaining(self):
        e = RateLimitEntry(key="k", window_seconds=60, max_requests=5)
        now = time.time()
        e.record(now)
        e.record(now)
        # remaining should be 3
        assert e.remaining >= 3

    def test_to_dict(self):
        e = RateLimitEntry(key="k", window_seconds=60, max_requests=5)
        d = e.to_dict()
        assert d["key"] == "k"
        assert d["max_requests"] == 5
        assert "remaining" in d
        assert "blocked" in d


class TestRateLimiter(unittest.TestCase):

    def test_create(self):
        rl = RateLimiter()
        assert rl.get_stats()["total_keys"] == 0

    def test_record_allowed(self):
        rl = RateLimiter()
        result = rl.record("user_1", "user")
        assert result == RateLimitResult.ALLOWED

    def test_record_limited(self):
        rl = RateLimiter()
        rl.set_limit("test", 2, 60.0)
        rl.record("k1", "test")
        rl.record("k1", "test")
        result = rl.record("k1", "test")
        assert result == RateLimitResult.LIMITED

    def test_block(self):
        rl = RateLimiter()
        rl.block("bad_user", 300, "user")
        result = rl.check("bad_user", "user")
        assert result == RateLimitResult.BLOCKED

    def test_get_status_key(self):
        rl = RateLimiter()
        rl.record("u1", "user")
        status = rl.get_status("u1")
        assert status["key"] == "u1"

    def test_get_status_all(self):
        rl = RateLimiter()
        rl.record("u1", "user")
        status = rl.get_status()
        assert "total_entries" in status

    def test_reset_key(self):
        rl = RateLimiter()
        rl.record("u1", "user")
        rl.reset("u1")
        assert rl.get_stats()["total_keys"] == 0

    def test_reset_all(self):
        rl = RateLimiter()
        rl.record("u1", "user")
        rl.record("u2", "user")
        rl.reset()
        assert rl.get_stats()["total_keys"] == 0

    def test_stats(self):
        rl = RateLimiter()
        stats = rl.get_stats()
        assert stats["total_limited"] == 0
        assert stats["currently_blocked"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# REQUEST TRACKER
# ═══════════════════════════════════════════════════════════════════════════════


class TestRequestRecord(unittest.TestCase):

    def test_create(self):
        r = RequestRecord(request_id="r1", user_id="u1",
                          action="test", started_at=time.time())
        assert r.success is True
        assert r.duration_ms == 0.0

    def test_finish(self):
        r = RequestRecord(request_id="r1", user_id="u1",
                          action="test", started_at=time.time() - 0.5)
        r.finish(success=True)
        assert r.duration_ms > 0
        assert r.finished_at > 0

    def test_finish_error(self):
        r = RequestRecord(request_id="r1", user_id="u1",
                          action="test", started_at=time.time())
        r.finish(success=False, error="boom")
        assert r.success is False
        assert r.error == "boom"


class TestRequestTracker(unittest.TestCase):

    def test_start_finish(self):
        rt = RequestTracker()
        req_id = rt.start_request("u1", "search")
        assert req_id.startswith("req_")
        rec = rt.finish_request(req_id)
        assert rec is not None
        assert rec.success is True

    def test_finish_nonexistent(self):
        rt = RequestTracker()
        rec = rt.finish_request("nonexistent")
        assert rec is None

    def test_stats(self):
        rt = RequestTracker()
        r1 = rt.start_request("u1", "a1")
        rt.finish_request(r1, success=True)
        r2 = rt.start_request("u1", "a2")
        rt.finish_request(r2, success=False, error="err")

        stats = rt.get_stats()
        assert stats["total_requests"] == 2
        assert stats["total_errors"] == 1
        assert stats["error_rate"] > 0

    def test_recent(self):
        rt = RequestTracker()
        r1 = rt.start_request("u1", "action1")
        rt.finish_request(r1)
        recent = rt.get_recent(5)
        assert len(recent) == 1
        assert recent[0]["action"] == "action1"

    def test_history_trim(self):
        rt = RequestTracker(max_history=5)
        for i in range(10):
            rid = rt.start_request("u1", f"a{i}")
            rt.finish_request(rid)
        assert len(rt._history) == 5


# ═══════════════════════════════════════════════════════════════════════════════
# HEALTH CHECKER
# ═══════════════════════════════════════════════════════════════════════════════


class TestSubsystemHealth(unittest.TestCase):

    def test_to_dict(self):
        sh = SubsystemHealth(name="db", status=HealthStatus.HEALTHY)
        d = sh.to_dict()
        assert d["name"] == "db"
        assert d["status"] == "healthy"


class TestHealthChecker(unittest.TestCase):

    def test_report_status(self):
        hc = HealthChecker()
        hc.report_status("db", HealthStatus.HEALTHY, "OK")
        assert hc.get_overall_status() == HealthStatus.HEALTHY

    def test_overall_degraded(self):
        hc = HealthChecker()
        hc.report_status("db", HealthStatus.HEALTHY)
        hc.report_status("llm", HealthStatus.DEGRADED)
        assert hc.get_overall_status() == HealthStatus.DEGRADED

    def test_overall_unhealthy(self):
        hc = HealthChecker()
        hc.report_status("db", HealthStatus.HEALTHY)
        hc.report_status("llm", HealthStatus.UNHEALTHY)
        assert hc.get_overall_status() == HealthStatus.UNHEALTHY

    def test_overall_unknown_empty(self):
        hc = HealthChecker()
        assert hc.get_overall_status() == HealthStatus.UNKNOWN

    def test_register_check_sync(self):
        hc = HealthChecker()
        hc.register_check("test", lambda: True)
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(hc.check_all())
            assert "test" in result
            assert result["test"].status == HealthStatus.HEALTHY
        finally:
            loop.close()

    def test_register_check_dict_result(self):
        hc = HealthChecker()
        hc.register_check("db", lambda: {
            "status": "degraded", "message": "slow"
        })
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(hc.check_all())
            assert result["db"].status == HealthStatus.DEGRADED
        finally:
            loop.close()

    def test_check_exception(self):
        hc = HealthChecker()
        hc.register_check("bad", lambda: 1 / 0)
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(hc.check_all())
            assert result["bad"].status == HealthStatus.UNHEALTHY
        finally:
            loop.close()

    def test_get_report(self):
        hc = HealthChecker()
        hc.report_status("db", HealthStatus.HEALTHY)
        report = hc.get_report()
        assert "overall" in report
        assert "subsystems" in report

    def test_get_stats(self):
        hc = HealthChecker()
        hc.report_status("x", HealthStatus.HEALTHY)
        stats = hc.get_stats()
        assert stats["subsystems"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# GRACEFUL SHUTDOWN
# ═══════════════════════════════════════════════════════════════════════════════


class TestShutdownTask(unittest.TestCase):

    def test_create(self):
        t = ShutdownTask(name="save", handler=lambda: None, priority=100)
        assert t.priority == 100
        assert t.timeout == 10.0


class TestGracefulShutdown(unittest.TestCase):

    def test_initial_state(self):
        gs = GracefulShutdown()
        assert gs.phase == ShutdownPhase.RUNNING
        assert gs.is_running is True
        assert gs.is_shutting_down is False

    def test_register(self):
        gs = GracefulShutdown()
        gs.register("save_mem", lambda: None, priority=100)
        gs.register("close_db", lambda: None, priority=10)
        assert gs.get_stats()["tasks_registered"] == 2

    def test_shutdown(self):
        gs = GracefulShutdown()
        executed = []

        async def save():
            executed.append("save")

        async def cleanup():
            executed.append("cleanup")

        gs.register("save", save, priority=100)
        gs.register("cleanup", cleanup, priority=0)

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(gs.shutdown(drain_timeout=0.1))
            assert gs.phase == ShutdownPhase.STOPPED
            assert "save" in executed
            assert "cleanup" in executed
            assert result["tasks_executed"] == 2
        finally:
            loop.close()

    def test_shutdown_timeout(self):
        gs = GracefulShutdown()

        async def slow():
            await asyncio.sleep(100)

        gs.register("slow", slow, priority=0, timeout=0.1)

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(gs.shutdown(drain_timeout=0.05))
            assert result["results"]["slow"]["success"] is False
            assert "Timeout" in result["results"]["slow"]["error"]
        finally:
            loop.close()

    def test_shutdown_error(self):
        gs = GracefulShutdown()

        def bad():
            raise ValueError("boom")

        gs.register("bad", bad, priority=0)

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(gs.shutdown(drain_timeout=0.05))
            assert result["results"]["bad"]["success"] is False
        finally:
            loop.close()


# ═══════════════════════════════════════════════════════════════════════════════
# ERROR REPORTER
# ═══════════════════════════════════════════════════════════════════════════════


class TestErrorEntry(unittest.TestCase):

    def test_create(self):
        e = ErrorEntry(error_type="ValueError", message="bad",
                       source="tools")
        assert e.count == 1
        assert e.last_seen > 0


class TestErrorReporter(unittest.TestCase):

    def test_report(self):
        er = ErrorReporter()
        er.report("TypeError", "oops", "agent")
        assert er.get_stats()["total_errors"] == 1

    def test_get_recent(self):
        er = ErrorReporter()
        er.report("A", "msg1", "s1")
        er.report("B", "msg2", "s2")
        recent = er.get_recent(5)
        assert len(recent) == 2
        assert recent[0]["type"] == "B"  # Most recent first

    def test_top_errors(self):
        er = ErrorReporter()
        er.report("A", "m", "s")
        er.report("A", "m", "s")
        er.report("B", "m", "s")
        top = er.get_top_errors(5)
        assert top[0]["type"] == "A"
        assert top[0]["count"] == 2

    def test_clear(self):
        er = ErrorReporter()
        er.report("X", "m", "s")
        er.clear()
        assert er.get_stats()["total_errors"] == 0

    def test_history_trim(self):
        er = ErrorReporter(max_history=5)
        for i in range(10):
            er.report("E", f"msg{i}", "s")
        assert len(er._errors) == 5
        assert er._total == 10


# ═══════════════════════════════════════════════════════════════════════════════
# STRUCTURED LOGGER
# ═══════════════════════════════════════════════════════════════════════════════


class TestLogEntry(unittest.TestCase):

    def test_to_dict(self):
        e = LogEntry(level="INFO", message="hello", source="test")
        d = e.to_dict()
        assert d["level"] == "INFO"
        assert d["msg"] == "hello"
        assert d["src"] == "test"

    def test_to_dict_no_source(self):
        e = LogEntry(level="ERROR", message="bad")
        d = e.to_dict()
        assert "src" not in d


class TestStructuredLogger(unittest.TestCase):

    def test_log(self):
        sl = StructuredLogger()
        sl.info("started", "main")
        sl.error("crash", "agent")
        stats = sl.get_stats()
        assert stats["total_entries"] == 2
        assert stats["by_level"]["INFO"] == 1
        assert stats["by_level"]["ERROR"] == 1

    def test_get_recent(self):
        sl = StructuredLogger()
        sl.info("a")
        sl.warning("b")
        recent = sl.get_recent(10)
        assert len(recent) == 2

    def test_get_recent_filtered(self):
        sl = StructuredLogger()
        sl.info("a")
        sl.error("b")
        sl.info("c")
        recent = sl.get_recent(10, level="ERROR")
        assert len(recent) == 1
        assert recent[0]["level"] == "ERROR"

    def test_debug(self):
        sl = StructuredLogger()
        entry = sl.debug("trace", user="u1")
        assert entry.level == "DEBUG"
        assert entry.extra == {"user": "u1"}

    def test_trim(self):
        sl = StructuredLogger(max_entries=3)
        for i in range(10):
            sl.info(f"msg{i}")
        assert len(sl._entries) == 3


# ═══════════════════════════════════════════════════════════════════════════════
# UPTIME MONITOR
# ═══════════════════════════════════════════════════════════════════════════════


class TestUptimeMonitor(unittest.TestCase):

    def test_uptime(self):
        um = UptimeMonitor()
        assert um.uptime_seconds > 0
        assert isinstance(um.uptime_human, str)

    def test_heartbeat(self):
        um = UptimeMonitor()
        um.heartbeat()
        stats = um.get_stats()
        assert stats["last_heartbeat_ago_s"] < 1.0

    def test_restart(self):
        um = UptimeMonitor()
        um.record_restart()
        um.record_restart()
        assert um.get_stats()["restarts"] == 2

    def test_downtime(self):
        um = UptimeMonitor()
        now = time.time()
        um.record_downtime(now - 100, now - 50)
        stats = um.get_stats()
        assert stats["total_downtime_s"] == 50.0

    def test_uptime_human_format(self):
        um = UptimeMonitor()
        # Just test it doesn't crash
        h = um.uptime_human
        assert "с" in h  # Should contain seconds


# ═══════════════════════════════════════════════════════════════════════════════
# SYSTEM METRICS
# ═══════════════════════════════════════════════════════════════════════════════


class TestSystemMetrics(unittest.TestCase):

    def test_memory_usage(self):
        m = SystemMetrics.get_memory_usage()
        assert "rss_mb" in m
        # On Linux /proc/self/status should work
        assert m["rss_mb"] >= 0

    def test_disk_usage(self):
        d = SystemMetrics.get_disk_usage("/tmp")
        assert "total_gb" in d
        assert d["total_gb"] > 0

    def test_load_average(self):
        la = SystemMetrics.get_load_average()
        assert "load_1m" in la

    def test_get_all(self):
        all_m = SystemMetrics.get_all()
        assert "memory" in all_m
        assert "disk" in all_m
        assert "load" in all_m


# ═══════════════════════════════════════════════════════════════════════════════
# ALERT MANAGER
# ═══════════════════════════════════════════════════════════════════════════════


class TestAlert(unittest.TestCase):

    def test_create(self):
        a = Alert(name="high_mem", severity=AlertSeverity.WARNING,
                  message="500MB")
        assert a.resolved is False

    def test_resolve(self):
        a = Alert(name="x", severity=AlertSeverity.INFO, message="m")
        a.resolve()
        assert a.resolved is True
        assert a.resolved_at > 0

    def test_to_dict(self):
        a = Alert(name="x", severity=AlertSeverity.CRITICAL, message="bad")
        d = a.to_dict()
        assert d["severity"] == "critical"
        assert d["resolved"] is False


class TestAlertManager(unittest.TestCase):

    def test_fire(self):
        am = AlertManager()
        alert = am.fire("test", AlertSeverity.WARNING, "msg")
        assert alert.name == "test"
        assert len(am.get_active()) == 1

    def test_resolve(self):
        am = AlertManager()
        am.fire("test", AlertSeverity.WARNING, "msg")
        ok = am.resolve("test")
        assert ok is True
        assert len(am.get_active()) == 0

    def test_resolve_nonexistent(self):
        am = AlertManager()
        assert am.resolve("nope") is False

    def test_check_thresholds_fire(self):
        am = AlertManager()
        metrics = {"memory": {"rss_mb": 600}}
        fired = am.check_thresholds(metrics)
        assert len(fired) >= 1
        assert any(a.name == "memory_high" for a in fired)

    def test_check_thresholds_resolve(self):
        am = AlertManager()
        # Fire first
        am.check_thresholds({"memory": {"rss_mb": 600}})
        assert "memory_high" in am._active
        # Resolve
        am.check_thresholds({"memory": {"rss_mb": 100}})
        assert "memory_high" not in am._active

    def test_check_disk_threshold(self):
        am = AlertManager()
        metrics = {"disk": {"usage_percent": 95}}
        fired = am.check_thresholds(metrics)
        assert any(a.name == "disk_full" for a in fired)

    def test_stats(self):
        am = AlertManager()
        stats = am.get_stats()
        assert stats["thresholds"] == 3


# ═══════════════════════════════════════════════════════════════════════════════
# PRODUCTION HARDENING (FACADE)
# ═══════════════════════════════════════════════════════════════════════════════


class TestProductionHardening(unittest.TestCase):

    def test_create(self):
        ph = ProductionHardening()
        assert ph.rate_limiter is not None
        assert ph.request_tracker is not None
        assert ph.health_checker is not None
        assert ph.shutdown is not None
        assert ph.error_reporter is not None
        assert ph.structured_logger is not None
        assert ph.uptime is not None
        assert ph.system_metrics is not None
        assert ph.alert_manager is not None

    def test_get_stats(self):
        ph = ProductionHardening()
        stats = ph.get_stats()
        assert "rate_limiter" in stats
        assert "requests" in stats
        assert "health" in stats
        assert "errors" in stats
        assert "uptime" in stats

    def test_system_report(self):
        ph = ProductionHardening()
        report = ph.get_system_report()
        assert "uptime" in report
        assert "health" in report
        assert "system" in report
        assert "requests" in report
        assert "alerts" in report

    def test_integration_flow(self):
        """Full flow: rate check → track request → report error → check health."""
        ph = ProductionHardening()

        # Rate limit check
        result = ph.rate_limiter.record("u1", "user")
        assert result == RateLimitResult.ALLOWED

        # Track request
        req_id = ph.request_tracker.start_request("u1", "search")
        ph.request_tracker.finish_request(
            req_id, success=False, error="timeout")

        # Report error
        ph.error_reporter.report("TimeoutError", "LLM timeout", "agent")

        # Log
        ph.structured_logger.error("LLM timeout", "agent", user="u1")

        # Health
        ph.health_checker.report_status("llm", HealthStatus.DEGRADED, "slow")

        # Verify
        stats = ph.get_stats()
        assert stats["requests"]["total_errors"] == 1
        assert stats["errors"]["total_errors"] == 1
        assert stats["health"]["overall"] == "degraded"


class TestGlobalInstance(unittest.TestCase):

    def test_production_singleton(self):
        assert production is not None
        assert isinstance(production, ProductionHardening)

    def test_production_has_all_components(self):
        assert production.rate_limiter is not None
        assert production.uptime is not None


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL COUNT
# ═══════════════════════════════════════════════════════════════════════════════


class TestPart12ToolCount(unittest.TestCase):

    def test_total_tool_count(self):
        """Всего 64 инструмента (60 Part 1-11 + 4 Part 12)."""
        from pds_ultimate.core.business_tools import register_all_tools
        from pds_ultimate.core.tools import ToolRegistry

        registry = ToolRegistry()
        from unittest.mock import patch
        with patch("pds_ultimate.core.business_tools.tool_registry", registry):
            count = register_all_tools()
            assert count == 64, f"Ожидалось 64, получено {count}"

    def test_part12_tools_exist(self):
        """Part 12 tools зарегистрированы."""
        from pds_ultimate.core.tools import tool_registry

        part12_names = [
            "system_health", "rate_limit_info",
            "error_report", "uptime_info",
        ]
        for name in part12_names:
            tool = tool_registry.get(name)
            assert tool is not None, f"Tool '{name}' не найден"
            assert tool.category == "production"


if __name__ == "__main__":
    unittest.main()
