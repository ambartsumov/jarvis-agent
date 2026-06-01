"""
Tests for Step 4: Dependency Injection Container
=================================================
Tests the DI Container: registration, resolution, lifecycle, overrides, health.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pds_ultimate.core.container import (
    Container,
    ServiceEntry,
    ServiceState,
    container,
)

# ═══════════════════════════════════════════════════════════════════════════════
# 1. ServiceState & ServiceEntry
# ═══════════════════════════════════════════════════════════════════════════════


class TestServiceState:
    """Test ServiceState enum."""

    def test_all_states(self):
        assert ServiceState.NOT_CREATED
        assert ServiceState.CREATED
        assert ServiceState.STARTED
        assert ServiceState.STOPPED
        assert ServiceState.FAILED

    def test_state_count(self):
        assert len(ServiceState) == 5


class TestServiceEntry:
    """Test ServiceEntry dataclass."""

    def test_defaults(self):
        entry = ServiceEntry(name="test", factory=lambda: None)
        assert entry.name == "test"
        assert entry.deps == []
        assert entry.instance is None
        assert entry.state == ServiceState.NOT_CREATED
        assert entry.start_method is None
        assert entry.stop_method is None
        assert entry.error is None
        assert entry.init_time_ms == 0.0
        assert entry.required is True

    def test_is_ready_not_created(self):
        entry = ServiceEntry(name="t", factory=lambda: None)
        assert entry.is_ready is False

    def test_is_ready_created(self):
        entry = ServiceEntry(
            name="t", factory=lambda: None,
            state=ServiceState.CREATED)
        assert entry.is_ready is True

    def test_is_ready_started(self):
        entry = ServiceEntry(
            name="t", factory=lambda: None,
            state=ServiceState.STARTED)
        assert entry.is_ready is True

    def test_is_ready_failed(self):
        entry = ServiceEntry(
            name="t", factory=lambda: None,
            state=ServiceState.FAILED)
        assert entry.is_ready is False

    def test_is_ready_stopped(self):
        entry = ServiceEntry(
            name="t", factory=lambda: None,
            state=ServiceState.STOPPED)
        assert entry.is_ready is False


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Container Registration
# ═══════════════════════════════════════════════════════════════════════════════


class TestContainerRegistration:
    """Test service registration."""

    def test_register_simple(self):
        c = Container()
        c.register("db", factory=lambda: {"engine": "sqlite"})
        assert c.has("db")

    def test_register_with_deps(self):
        c = Container()
        c.register("db", factory=lambda: "db_engine")
        c.register(
            "repo", factory=lambda db: f"repo({db})",
            deps=["db"])
        assert c.has("repo")

    def test_register_instance(self):
        c = Container()
        obj = {"key": "value"}
        c.register_instance("config", obj)
        assert c.resolve("config") is obj

    def test_register_overwrite_warning(self):
        c = Container()
        c.register("x", factory=lambda: 1)
        c.register("x", factory=lambda: 2)
        assert c.resolve("x") == 2

    def test_has_unregistered(self):
        c = Container()
        assert c.has("nonexistent") is False


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Container Resolution
# ═══════════════════════════════════════════════════════════════════════════════


class TestContainerResolution:
    """Test lazy singleton resolution."""

    def test_resolve_simple(self):
        c = Container()
        c.register("val", factory=lambda: 42)
        assert c.resolve("val") == 42

    def test_resolve_singleton(self):
        """Factory called only once — same instance returned."""
        c = Container()
        calls = []

        def factory():
            calls.append(1)
            return {"data": "value"}

        c.register("svc", factory=factory)
        a = c.resolve("svc")
        b = c.resolve("svc")
        assert a is b
        assert len(calls) == 1

    def test_resolve_with_deps(self):
        c = Container()
        c.register("db", factory=lambda: "sqlite://memory")
        c.register(
            "repo",
            factory=lambda db: f"UserRepo({db})",
            deps=["db"],
        )
        result = c.resolve("repo")
        assert result == "UserRepo(sqlite://memory)"

    def test_resolve_chain(self):
        """A → B → C dependency chain."""
        c = Container()
        c.register("c", factory=lambda: "C")
        c.register("b", factory=lambda c: f"B({c})", deps=["c"])
        c.register("a", factory=lambda b: f"A({b})", deps=["b"])
        assert c.resolve("a") == "A(B(C))"

    def test_resolve_unregistered_raises(self):
        c = Container()
        with pytest.raises(KeyError, match="not registered"):
            c.resolve("missing")

    def test_resolve_attr_syntax(self):
        """container.service_name syntax."""
        c = Container()
        c.register("my_service", factory=lambda: "hello")
        assert c.my_service == "hello"

    def test_resolve_attr_unregistered_raises(self):
        c = Container()
        with pytest.raises(AttributeError, match="not registered"):
            _ = c.nonexistent

    def test_resolve_failed_required_raises(self):
        c = Container()
        c.register(
            "bad", factory=lambda: (_ for _ in ()).throw(ValueError("boom")))
        with pytest.raises(RuntimeError, match="Failed to create"):
            c.resolve("bad")

    def test_resolve_failed_optional_returns_none(self):
        c = Container()
        c.register(
            "opt",
            factory=lambda: (_ for _ in ()).throw(ValueError("fail")),
            required=False,
        )
        result = c.resolve("opt")
        assert result is None

    def test_resolve_missing_dep_required_raises(self):
        c = Container()
        c.register("svc", factory=lambda db: db, deps=["db"])
        with pytest.raises(RuntimeError, match="resolve dependency"):
            c.resolve("svc")

    def test_resolve_missing_dep_optional_ok(self):
        c = Container()
        c.register(
            "svc",
            factory=lambda: "fallback",
            deps=["missing_dep"],
            required=False,
        )
        result = c.resolve("svc")
        # factory gets called without the dep kwargs since dep is missing
        assert result == "fallback"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Overrides (for testing)
# ═══════════════════════════════════════════════════════════════════════════════


class TestContainerOverrides:
    """Test override mechanism for testing."""

    def test_override_replaces(self):
        c = Container()
        c.register("db", factory=lambda: "real_db")
        c.override("db", "mock_db")
        assert c.resolve("db") == "mock_db"

    def test_override_without_register(self):
        c = Container()
        c.override("fake", "value")
        assert c.resolve("fake") == "value"

    def test_override_has(self):
        c = Container()
        c.override("x", 1)
        assert c.has("x") is True

    def test_reset_overrides(self):
        c = Container()
        c.register("db", factory=lambda: "real")
        c.override("db", "mock")
        assert c.resolve("db") == "mock"
        c.reset_overrides()
        assert c.resolve("db") == "real"

    def test_override_priority(self):
        """Override always wins over factory."""
        c = Container()
        c.register("svc", factory=lambda: "factory_value")
        c.override("svc", "override_value")
        assert c.resolve("svc") == "override_value"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Lifecycle (start/stop)
# ═══════════════════════════════════════════════════════════════════════════════


class TestContainerLifecycle:
    """Test async start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_no_services(self):
        c = Container()
        warnings = await c.start()
        assert warnings == []

    @pytest.mark.asyncio
    async def test_start_simple_service(self):
        c = Container()
        mock = MagicMock()
        mock.start = AsyncMock()
        c.register(
            "svc", factory=lambda: mock,
            start_method="start")
        warnings = await c.start()
        assert warnings == []
        mock.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_calls_stop_method(self):
        c = Container()
        mock = MagicMock()
        mock.start = AsyncMock()
        mock.stop = AsyncMock()
        c.register(
            "svc", factory=lambda: mock,
            start_method="start", stop_method="stop")
        await c.start()
        await c.stop()
        mock.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_order_respects_deps(self):
        """Services start in dependency order."""
        c = Container()
        order = []

        class SvcA:
            def __init__(self, **kw):
                pass

            async def start(self):
                order.append("a")

        class SvcB:
            async def start(self):
                order.append("b")

        c.register(
            "b", factory=SvcB, start_method="start")
        c.register(
            "a", factory=SvcA, deps=["b"],
            start_method="start")

        await c.start()
        # B should start before A
        assert order.index("b") < order.index("a")

    @pytest.mark.asyncio
    async def test_start_failed_required_raises(self):
        c = Container()
        mock = MagicMock()
        mock.start = AsyncMock(side_effect=ConnectionError("fail"))
        c.register(
            "db", factory=lambda: mock,
            start_method="start", required=True)

        with pytest.raises(RuntimeError, match="Failed to start"):
            await c.start()

    @pytest.mark.asyncio
    async def test_start_failed_optional_warns(self):
        c = Container()
        mock = MagicMock()
        mock.start = AsyncMock(side_effect=ConnectionError("fail"))
        c.register(
            "optional_svc", factory=lambda: mock,
            start_method="start", required=False)

        warnings = await c.start()
        assert len(warnings) == 1
        assert "optional_svc" in warnings[0]

    @pytest.mark.asyncio
    async def test_stop_in_reverse_order(self):
        c = Container()
        order = []

        class SvcA:
            async def stop(self):
                order.append("a")

        class SvcB:
            def __init__(self, **kw):
                pass

            async def stop(self):
                order.append("b")

        c.register("a", factory=SvcA, stop_method="stop")
        c.register("b", factory=SvcB, deps=["a"], stop_method="stop")
        await c.start()
        await c.stop()
        # B depends on A, so B should stop first (reverse order)
        assert order.index("b") < order.index("a")

    @pytest.mark.asyncio
    async def test_stop_error_does_not_crash(self):
        c = Container()
        mock = MagicMock()
        mock.stop = AsyncMock(side_effect=RuntimeError("crash"))
        c.register(
            "svc", factory=lambda: mock, stop_method="stop")
        await c.start()
        # Should not raise
        await c.stop()

    @pytest.mark.asyncio
    async def test_start_sets_started_flag(self):
        c = Container()
        assert c._started is False
        await c.start()
        assert c._started is True
        await c.stop()
        assert c._started is False


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Topological Sort
# ═══════════════════════════════════════════════════════════════════════════════


class TestTopologicalSort:
    """Test dependency ordering."""

    def test_no_deps(self):
        c = Container()
        c.register("a", factory=lambda: None)
        c.register("b", factory=lambda: None)
        order = c._topological_sort()
        assert set(order) == {"a", "b"}

    def test_linear_chain(self):
        c = Container()
        c.register("c", factory=lambda: None)
        c.register("b", factory=lambda: None, deps=["c"])
        c.register("a", factory=lambda: None, deps=["b"])
        order = c._topological_sort()
        assert order.index("c") < order.index("b")
        assert order.index("b") < order.index("a")

    def test_diamond(self):
        """A depends on B and C, both depend on D."""
        c = Container()
        c.register("d", factory=lambda: None)
        c.register("b", factory=lambda: None, deps=["d"])
        c.register("c", factory=lambda: None, deps=["d"])
        c.register("a", factory=lambda: None, deps=["b", "c"])
        order = c._topological_sort()
        assert order.index("d") < order.index("b")
        assert order.index("d") < order.index("c")
        assert order.index("b") < order.index("a")
        assert order.index("c") < order.index("a")

    def test_cycle_handled_gracefully(self):
        """Circular dependency doesn't crash — best effort."""
        c = Container()
        c.register("a", factory=lambda: None, deps=["b"])
        c.register("b", factory=lambda: None, deps=["a"])
        order = c._topological_sort()
        assert len(order) == 2
        assert set(order) == {"a", "b"}

    def test_external_dep_ignored(self):
        """Dependencies not in registry are ignored in sort."""
        c = Container()
        c.register("a", factory=lambda: None, deps=["external"])
        order = c._topological_sort()
        assert order == ["a"]


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Health & Stats
# ═══════════════════════════════════════════════════════════════════════════════


class TestContainerHealth:
    """Test health check and stats."""

    def test_health_empty(self):
        c = Container()
        health = c.get_health()
        assert health["overall"] == "healthy"
        assert health["services_total"] == 0
        assert health["services_healthy"] == 0

    def test_health_with_services(self):
        c = Container()
        c.register("a", factory=lambda: 1)
        c.resolve("a")
        health = c.get_health()
        assert health["services_total"] == 1
        assert health["services_healthy"] == 1

    def test_health_with_failure(self):
        c = Container()
        c.register(
            "bad",
            factory=lambda: (_ for _ in ()).throw(ValueError("boom")),
            required=False,
        )
        c.resolve("bad")
        health = c.get_health()
        assert health["overall"] == "degraded"
        assert health["services_failed"] == 1

    def test_stats(self):
        c = Container()
        c.register("a", factory=lambda: 1)
        c.register("b", factory=lambda: 2)
        c.resolve("a")
        stats = c.get_stats()
        assert stats["total"] == 2
        assert stats["created"] == 1  # only 'a' resolved

    def test_stats_overrides(self):
        c = Container()
        c.override("x", "mock")
        stats = c.get_stats()
        assert stats["overrides"] == 1

    def test_repr(self):
        c = Container()
        c.register("a", factory=lambda: 1)
        repr_str = repr(c)
        assert "Container" in repr_str
        assert "services=1" in repr_str


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Global Instance
# ═══════════════════════════════════════════════════════════════════════════════


class TestGlobalContainer:
    """Test global container instance."""

    def test_global_exists(self):
        assert container is not None
        assert isinstance(container, Container)

    def test_global_importable(self):
        from pds_ultimate.core.container import container as c2
        assert c2 is container


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Integration: Real-world patterns
# ═══════════════════════════════════════════════════════════════════════════════


class TestContainerIntegration:
    """Test real-world usage patterns."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        """Register → Start → Use → Stop."""
        c = Container()

        class Database:
            def __init__(self):
                self.connected = False

            async def start(self):
                self.connected = True

            async def stop(self):
                self.connected = False

        class UserRepo:
            def __init__(self, db):
                self.db = db

            def find(self, user_id: int):
                return f"User-{user_id}" if self.db.connected else None

        c.register(
            "db", factory=Database,
            start_method="start", stop_method="stop")
        c.register(
            "user_repo",
            factory=lambda db: UserRepo(db),
            deps=["db"],
        )

        await c.start()
        repo = c.resolve("user_repo")
        assert repo.find(1) == "User-1"
        await c.stop()
        assert repo.db.connected is False

    def test_override_for_testing(self):
        """Override pattern for unit tests."""
        c = Container()
        c.register("llm", factory=lambda: "real_llm")
        c.register(
            "agent",
            factory=lambda llm: f"Agent({llm})",
            deps=["llm"],
        )

        # Without override
        assert c.resolve("agent") == "Agent(real_llm)"

        # Reset for override test
        c2 = Container()
        c2.register("llm", factory=lambda: "real_llm")
        c2.register(
            "agent",
            factory=lambda llm: f"Agent({llm})",
            deps=["llm"],
        )
        c2.override("llm", "mock_llm")
        assert c2.resolve("agent") == "Agent(mock_llm)"

    @pytest.mark.asyncio
    async def test_mixed_required_optional(self):
        """Mix of required and optional services."""
        c = Container()
        c.register("core", factory=lambda: "core_ok")
        c.register(
            "optional_ext",
            factory=lambda: (_ for _ in ()).throw(ImportError("no module")),
            required=False,
        )

        warnings = await c.start()
        assert c.resolve("core") == "core_ok"
        # optional failed but didn't crash start
        health = c.get_health()
        assert health["services_failed"] == 1
        assert health["overall"] == "degraded"

    def test_service_init_timing(self):
        """Init time is tracked."""
        c = Container()
        c.register("svc", factory=lambda: "value")
        c.resolve("svc")
        entry = c._registry["svc"]
        assert entry.init_time_ms >= 0
