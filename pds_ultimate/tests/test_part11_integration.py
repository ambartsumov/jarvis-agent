"""
Tests for Part 11 — Integration Layer
"""

import asyncio
import time

import pytest

from pds_ultimate.core.integration_layer import (
    AutoHealer,
    ChainExecutor,
    ChainResult,
    ChainStatus,
    ChainStep,
    CircuitBreaker,
    FallbackManager,
    HealthMonitor,
    IntegrationLayer,
    ResultAggregator,
    RetryPolicy,
    StepResult,
    ToolChain,
    ToolChainRouter,
    ToolHealth,
    ToolMetrics,
    integration_layer,
)

# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


class FakeToolResult:
    """Имитация ToolResult."""

    def __init__(self, success=True, output="ok", data=None, error=""):
        self.success = success
        self.output = output
        self.data = data
        self.error = error


async def fake_executor_ok(name: str, params: dict = None, db=None):
    """Успешный имитатор tool_registry.execute."""
    return FakeToolResult(
        success=True, output=f"Result of {name}", data={"tool": name},
    )


async def fake_executor_fail(name: str, params: dict = None, db=None):
    """Неуспешный имитатор."""
    return FakeToolResult(
        success=False, output="", error=f"Tool {name} failed",
    )


async def fake_executor_mixed(name: str, params: dict = None, db=None):
    """Имитатор: чётные вызовы OK, нечётные FAIL."""
    if not hasattr(fake_executor_mixed, "_call_count"):
        fake_executor_mixed._call_count = 0
    fake_executor_mixed._call_count += 1
    if fake_executor_mixed._call_count % 2 == 0:
        return FakeToolResult(success=True, output=f"OK {name}")
    return FakeToolResult(success=False, error=f"FAIL {name}")


async def fake_executor_slow(name: str, params: dict = None, db=None):
    """Медленный имитатор (для тестов timeout)."""
    await asyncio.sleep(5)
    return FakeToolResult(success=True, output="slow")


# ═══════════════════════════════════════════════════════════════════════════════
# CHAIN STEP
# ═══════════════════════════════════════════════════════════════════════════════


class TestChainStep:
    """Тесты ChainStep."""

    def test_create(self):
        step = ChainStep(tool_name="web_search", params={"query": "test"})
        assert step.tool_name == "web_search"
        assert step.params["query"] == "test"
        assert step.optional is False

    def test_to_dict(self):
        step = ChainStep(tool_name="t1", params={"a": 1}, optional=True)
        d = step.to_dict()
        assert d["tool"] == "t1"
        assert d["optional"] is True

    def test_param_mapping(self):
        step = ChainStep(
            tool_name="summarize_text",
            param_mapping={"text": "prev.output"},
        )
        assert step.param_mapping["text"] == "prev.output"


# ═══════════════════════════════════════════════════════════════════════════════
# STEP RESULT
# ═══════════════════════════════════════════════════════════════════════════════


class TestStepResult:
    """Тесты StepResult."""

    def test_create_success(self):
        r = StepResult(step_index=0, tool_name="t1", success=True, output="ok")
        assert r.success
        assert r.step_index == 0

    def test_create_failure(self):
        r = StepResult(step_index=1, tool_name="t2",
                       success=False, error="err")
        assert not r.success
        assert r.error == "err"

    def test_to_dict(self):
        r = StepResult(
            step_index=0, tool_name="t", success=True,
            output="x" * 300, duration_ms=150,
        )
        d = r.to_dict()
        assert len(d["output"]) <= 200
        assert d["duration_ms"] == 150


# ═══════════════════════════════════════════════════════════════════════════════
# CHAIN RESULT
# ═══════════════════════════════════════════════════════════════════════════════


class TestChainResult:
    """Тесты ChainResult."""

    def test_empty(self):
        cr = ChainResult(
            chain_id="c1", chain_name="test",
            status=ChainStatus.COMPLETED,
        )
        assert cr.success_rate == 0.0
        assert cr.failed_steps == []

    def test_success_rate(self):
        cr = ChainResult(
            chain_id="c2", chain_name="test",
            status=ChainStatus.PARTIAL,
            steps=[
                StepResult(0, "t1", True),
                StepResult(1, "t2", False, error="e"),
                StepResult(2, "t3", True),
            ],
        )
        assert cr.success_rate == pytest.approx(2 / 3, abs=0.01)
        assert len(cr.failed_steps) == 1

    def test_to_dict(self):
        cr = ChainResult(
            chain_id="c3", chain_name="n",
            status=ChainStatus.COMPLETED,
            total_duration_ms=500,
        )
        d = cr.to_dict()
        assert d["name"] == "n"
        assert d["total_duration_ms"] == 500


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL CHAIN
# ═══════════════════════════════════════════════════════════════════════════════


class TestToolChain:
    """Тесты ToolChain."""

    def test_create(self):
        chain = ToolChain(name="test_chain")
        assert chain.name == "test_chain"
        assert len(chain.steps) == 0

    def test_add_step(self):
        chain = ToolChain(name="c")
        chain.add_step("t1", {"a": 1})
        chain.add_step("t2", param_mapping={"x": "prev.output"})
        assert len(chain.steps) == 2
        assert chain.steps[1].param_mapping["x"] == "prev.output"

    def test_fluent_api(self):
        chain = (
            ToolChain(name="fluent")
            .add_step("a")
            .add_step("b")
            .add_step("c")
        )
        assert len(chain.steps) == 3

    def test_to_dict(self):
        chain = ToolChain(
            name="d", description="desc", tags=["x"],
        )
        chain.add_step("t1")
        d = chain.to_dict()
        assert d["name"] == "d"
        assert len(d["steps"]) == 1
        assert d["tags"] == ["x"]


# ═══════════════════════════════════════════════════════════════════════════════
# RETRY POLICY
# ═══════════════════════════════════════════════════════════════════════════════


class TestRetryPolicy:
    """Тесты RetryPolicy."""

    def test_default(self):
        rp = RetryPolicy()
        assert rp.max_retries == 3
        assert rp.jitter is True

    def test_get_delay(self):
        rp = RetryPolicy(base_delay=1.0, jitter=False)
        assert rp.get_delay(0) == 1.0
        assert rp.get_delay(1) == 2.0
        assert rp.get_delay(2) == 4.0

    def test_max_delay(self):
        rp = RetryPolicy(base_delay=1.0, max_delay=5.0, jitter=False)
        assert rp.get_delay(10) == 5.0

    def test_jitter(self):
        rp = RetryPolicy(base_delay=1.0, jitter=True)
        delays = [rp.get_delay(0) for _ in range(10)]
        # С jitter задержки не все одинаковые
        assert len(set(round(d, 3) for d in delays)) > 1

    def test_to_dict(self):
        rp = RetryPolicy()
        d = rp.to_dict()
        assert "max_retries" in d
        assert "jitter" in d


# ═══════════════════════════════════════════════════════════════════════════════
# CIRCUIT BREAKER
# ═══════════════════════════════════════════════════════════════════════════════


class TestCircuitBreaker:
    """Тесты CircuitBreaker."""

    def test_initial_state(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitBreaker.State.CLOSED
        assert cb.is_available is True

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitBreaker.State.OPEN
        assert cb.is_available is False

    def test_stays_closed_below_threshold(self):
        cb = CircuitBreaker(failure_threshold=5)
        for _ in range(4):
            cb.record_failure()
        assert cb.state == CircuitBreaker.State.CLOSED

    def test_success_resets_failures(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        cb.record_failure()
        # After success, count resets, so 2 failures < 3
        assert cb.state == CircuitBreaker.State.CLOSED

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.01)
        cb.record_failure()
        cb.record_failure()
        assert cb._state == CircuitBreaker.State.OPEN
        time.sleep(0.02)
        assert cb.state == CircuitBreaker.State.HALF_OPEN

    def test_half_open_to_closed(self):
        cb = CircuitBreaker(
            failure_threshold=2, recovery_timeout=0.01,
            success_threshold=1,
        )
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.02)
        assert cb.state == CircuitBreaker.State.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitBreaker.State.CLOSED

    def test_half_open_to_open(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.01)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.02)
        _ = cb.state  # triggers HALF_OPEN
        cb.record_failure()
        assert cb._state == CircuitBreaker.State.OPEN

    def test_reset(self):
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure()
        assert cb.state == CircuitBreaker.State.OPEN
        cb.reset()
        assert cb.state == CircuitBreaker.State.CLOSED

    def test_get_stats(self):
        cb = CircuitBreaker()
        cb.record_success()
        cb.record_failure()
        stats = cb.get_stats()
        assert stats["total_calls"] == 2
        assert stats["total_failures"] == 1
        assert stats["failure_rate"] == 0.5


# ═══════════════════════════════════════════════════════════════════════════════
# FALLBACK MANAGER
# ═══════════════════════════════════════════════════════════════════════════════


class TestFallbackManager:
    """Тесты FallbackManager."""

    def test_register(self):
        fm = FallbackManager()
        fm.register("tool_a", ["tool_b", "tool_c"])
        assert fm.get_fallbacks("tool_a") == ["tool_b", "tool_c"]

    def test_no_fallback(self):
        fm = FallbackManager()
        assert fm.get_fallbacks("unknown") == []

    def test_get_next_fallback(self):
        fm = FallbackManager()
        fm.register("t1", ["t2", "t3"])
        assert fm.get_next_fallback("t1") == "t2"
        assert fm.get_next_fallback("t1", tried={"t2"}) == "t3"
        assert fm.get_next_fallback("t1", tried={"t2", "t3"}) is None

    def test_register_defaults(self):
        fm = FallbackManager()
        fm.register_defaults()
        assert len(fm.get_fallbacks("web_search")) > 0

    def test_get_stats(self):
        fm = FallbackManager()
        fm.register("a", ["b"])
        stats = fm.get_stats()
        assert stats["registered"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# HEALTH MONITOR
# ═══════════════════════════════════════════════════════════════════════════════


class TestToolMetrics:
    """Тесты ToolMetrics."""

    def test_initial(self):
        m = ToolMetrics(tool_name="test")
        assert m.health == ToolHealth.UNKNOWN
        assert m.avg_response_ms == 0.0
        assert m.failure_rate == 0.0

    def test_record_success(self):
        m = ToolMetrics(tool_name="t")
        m.record_call(True, 100)
        assert m.total_calls == 1
        assert m.health == ToolHealth.HEALTHY

    def test_record_failure(self):
        m = ToolMetrics(tool_name="t")
        for _ in range(10):
            m.record_call(False, 50, "err")
        assert m.failure_rate == 1.0
        assert m.health == ToolHealth.UNHEALTHY

    def test_degraded(self):
        m = ToolMetrics(tool_name="t")
        m.record_call(True, 100)
        m.record_call(True, 100)
        m.record_call(False, 100, "e")
        # 1/3 failures = 0.33 > 0.2 → DEGRADED
        assert m.health == ToolHealth.DEGRADED

    def test_avg_response(self):
        m = ToolMetrics(tool_name="t")
        m.record_call(True, 100)
        m.record_call(True, 200)
        assert m.avg_response_ms == 150.0

    def test_to_dict(self):
        m = ToolMetrics(tool_name="t")
        m.record_call(True, 50)
        d = m.to_dict()
        assert d["tool"] == "t"
        assert d["calls"] == 1


class TestHealthMonitor:
    """Тесты HealthMonitor."""

    def test_record(self):
        hm = HealthMonitor()
        hm.record("t1", True, 100)
        assert hm.get_health("t1") == ToolHealth.HEALTHY

    def test_unknown(self):
        hm = HealthMonitor()
        assert hm.get_health("unknown") == ToolHealth.UNKNOWN

    def test_unhealthy_list(self):
        hm = HealthMonitor()
        for _ in range(10):
            hm.record("bad_tool", False, 50, "err")
        assert "bad_tool" in hm.get_unhealthy()

    def test_get_all_metrics(self):
        hm = HealthMonitor()
        hm.record("a", True, 10)
        hm.record("b", False, 20, "e")
        metrics = hm.get_all_metrics()
        assert len(metrics) == 2

    def test_top_slow(self):
        hm = HealthMonitor()
        hm.record("fast", True, 10)
        hm.record("slow", True, 5000)
        slow = hm.get_top_slow(1)
        assert slow[0]["tool"] == "slow"

    def test_top_failing(self):
        hm = HealthMonitor()
        hm.record("good", True, 10)
        hm.record("bad", False, 10, "e")
        failing = hm.get_top_failing(1)
        assert failing[0]["tool"] == "bad"

    def test_get_stats(self):
        hm = HealthMonitor()
        hm.record("t1", True, 50)
        stats = hm.get_stats()
        assert stats["total_tools_tracked"] == 1
        assert stats["total_calls"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# RESULT AGGREGATOR
# ═══════════════════════════════════════════════════════════════════════════════


class TestResultAggregator:
    """Тесты ResultAggregator."""

    def test_aggregate_text(self):
        results = [
            StepResult(0, "t1", True, output="Hello"),
            StepResult(1, "t2", True, output="World"),
            StepResult(2, "t3", False, error="err"),
        ]
        text = ResultAggregator.aggregate_text(results)
        assert "Hello" in text
        assert "World" in text

    def test_aggregate_data(self):
        results = [
            StepResult(0, "t1", True, data={"a": 1}),
            StepResult(1, "t2", True, data={"b": 2}),
        ]
        data = ResultAggregator.aggregate_data(results)
        assert "t1" in data
        assert data["t1"]["a"] == 1

    def test_summary(self):
        results = [
            StepResult(0, "t1", True),
            StepResult(1, "t2", False, error="err"),
        ]
        s = ResultAggregator.summary(results)
        assert "1/2" in s
        assert "t2" in s


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL CHAIN ROUTER
# ═══════════════════════════════════════════════════════════════════════════════


class TestToolChainRouter:
    """Тесты ToolChainRouter."""

    def test_register_and_get(self):
        router = ToolChainRouter()
        chain = ToolChain(name="test_chain")
        router.register_chain(chain)
        assert router.get_chain("test_chain") is not None

    def test_find_by_keyword(self):
        router = ToolChainRouter()
        chain = ToolChain(name="research")
        router.register_chain(chain, ["исследуй", "найди"])
        found = router.find_chain("исследуй тренды AI")
        assert found is not None
        assert found.name == "research"

    def test_find_no_match(self):
        router = ToolChainRouter()
        assert router.find_chain("random text") is None

    def test_register_defaults(self):
        router = ToolChainRouter()
        router.register_defaults()
        assert router.get_chain("research_summarize") is not None
        assert len(router.list_chains()) >= 3

    def test_get_stats(self):
        router = ToolChainRouter()
        router.register_defaults()
        stats = router.get_stats()
        assert stats["total_chains"] >= 3
        assert stats["keyword_routes"] > 0


# ═══════════════════════════════════════════════════════════════════════════════
# CHAIN EXECUTOR
# ═══════════════════════════════════════════════════════════════════════════════


class TestChainExecutor:
    """Тесты ChainExecutor."""

    @pytest.mark.asyncio
    async def test_execute_simple_chain(self):
        hm = HealthMonitor()
        fm = FallbackManager()
        ex = ChainExecutor(hm, fm)

        chain = ToolChain(name="simple").add_step("t1").add_step("t2")
        result = await ex.execute_chain(chain, fake_executor_ok)
        assert result.status == ChainStatus.COMPLETED
        assert len(result.steps) == 2
        assert all(s.success for s in result.steps)

    @pytest.mark.asyncio
    async def test_execute_chain_with_failure(self):
        hm = HealthMonitor()
        fm = FallbackManager()
        ex = ChainExecutor(hm, fm, default_retry=RetryPolicy(max_retries=0))

        chain = ToolChain(name="fail").add_step("t1")
        result = await ex.execute_chain(chain, fake_executor_fail)
        assert result.status == ChainStatus.FAILED

    @pytest.mark.asyncio
    async def test_optional_step_skipped(self):
        hm = HealthMonitor()
        fm = FallbackManager()
        ex = ChainExecutor(hm, fm, default_retry=RetryPolicy(max_retries=0))

        chain = ToolChain(name="opt", abort_policy="never")
        chain.add_step("t1")  # will fail
        chain.add_step("t2", optional=True)  # optional, will also fail

        result = await ex.execute_chain(chain, fake_executor_fail)
        # abort_policy=never → runs all steps
        assert len(result.steps) == 2

    @pytest.mark.asyncio
    async def test_param_mapping_prev(self):
        hm = HealthMonitor()
        fm = FallbackManager()
        ex = ChainExecutor(hm, fm)

        chain = ToolChain(name="map")
        chain.add_step("t1", params={"query": "hello"})
        chain.add_step(
            "t2", param_mapping={"text": "prev.output"},
        )

        result = await ex.execute_chain(chain, fake_executor_ok)
        assert result.status == ChainStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_param_mapping_input(self):
        hm = HealthMonitor()
        fm = FallbackManager()
        ex = ChainExecutor(hm, fm)

        chain = ToolChain(name="inp")
        chain.add_step("t1", param_mapping={"query": "input.query"})

        result = await ex.execute_chain(
            chain, fake_executor_ok, {"query": "test query"},
        )
        assert result.status == ChainStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_abort_policy_any_fail(self):
        hm = HealthMonitor()
        fm = FallbackManager()
        ex = ChainExecutor(hm, fm, default_retry=RetryPolicy(max_retries=0))

        chain = ToolChain(name="abort", abort_policy="any_fail")
        chain.add_step("t1")  # fail
        chain.add_step("t2")  # should not run

        result = await ex.execute_chain(chain, fake_executor_fail)
        assert result.status == ChainStatus.FAILED
        assert len(result.steps) == 1  # Only first step

    @pytest.mark.asyncio
    async def test_fallback_used(self):
        hm = HealthMonitor()
        fm = FallbackManager()
        fm.register("bad_tool", ["good_tool"])
        ex = ChainExecutor(hm, fm, default_retry=RetryPolicy(max_retries=0))

        call_log = []

        async def selective_executor(name, params=None, db=None):
            call_log.append(name)
            if name == "bad_tool":
                return FakeToolResult(False, error="broken")
            return FakeToolResult(True, output="ok from fallback")

        chain = ToolChain(name="fb").add_step("bad_tool")
        result = await ex.execute_chain(chain, selective_executor)
        assert result.steps[0].success
        assert "good_tool" in call_log

    @pytest.mark.asyncio
    async def test_timeout(self):
        hm = HealthMonitor()
        fm = FallbackManager()
        ex = ChainExecutor(hm, fm, default_retry=RetryPolicy(max_retries=0))

        chain = ToolChain(name="to")
        chain.add_step("slow", timeout=0.05)

        result = await ex.execute_chain(chain, fake_executor_slow)
        assert result.status == ChainStatus.FAILED
        assert "timeout" in result.steps[0].error.lower()

    @pytest.mark.asyncio
    async def test_get_stats(self):
        hm = HealthMonitor()
        fm = FallbackManager()
        ex = ChainExecutor(hm, fm)
        chain = ToolChain(name="s").add_step("t1")
        await ex.execute_chain(chain, fake_executor_ok)
        stats = ex.get_stats()
        assert stats["total_executions"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# AUTO HEALER
# ═══════════════════════════════════════════════════════════════════════════════


class TestAutoHealer:
    """Тесты AutoHealer."""

    def test_diagnose_timeout(self):
        ah = AutoHealer()
        s = ah.diagnose("t1", "Connection timeout")
        assert s == AutoHealer.Strategy.REFINE_PARAMS

    def test_diagnose_rate_limit(self):
        ah = AutoHealer()
        s = ah.diagnose("t1", "Rate limit exceeded")
        assert s == AutoHealer.Strategy.CACHE_FALLBACK

    def test_diagnose_permission(self):
        ah = AutoHealer()
        s = ah.diagnose("t1", "Permission denied")
        assert s == AutoHealer.Strategy.GIVE_UP

    def test_diagnose_unknown(self):
        ah = AutoHealer()
        s = ah.diagnose("t1", "Something weird happened")
        assert s == AutoHealer.Strategy.ALTERNATIVE

    def test_refine_params_timeout(self):
        ah = AutoHealer()
        params = {"text": "x" * 500, "query": "hello"}
        refined = ah.refine_params(params, "timeout")
        assert len(refined["text"]) <= 200
        assert refined["query"] == "hello"

    def test_refine_params_validation(self):
        ah = AutoHealer()
        params = {"text": "Hello! @#$ World"}
        refined = ah.refine_params(params, "validation error")
        assert "@" not in refined["text"]
        assert "#" not in refined["text"]

    def test_cache(self):
        ah = AutoHealer()
        ah.cache_result("key1", {"answer": 42})
        result = ah.get_cached("key1")
        assert result == {"answer": 42}

    def test_cache_miss(self):
        ah = AutoHealer()
        assert ah.get_cached("nonexistent") is None

    def test_cache_expired(self):
        ah = AutoHealer()
        ah.cache_result("old", "data")
        result = ah.get_cached("old", max_age=0)
        assert result is None

    def test_record_healing(self):
        ah = AutoHealer()
        ah.record_healing(True)
        ah.record_healing(False)
        stats = ah.get_stats()
        assert stats["total_healings"] == 2
        assert stats["successful"] == 1
        assert stats["success_rate"] == 0.5


# ═══════════════════════════════════════════════════════════════════════════════
# INTEGRATION LAYER FACADE
# ═══════════════════════════════════════════════════════════════════════════════


class TestIntegrationLayer:
    """Тесты IntegrationLayer фасада."""

    def test_create(self):
        layer = IntegrationLayer()
        assert not layer.is_initialized

    def test_initialize(self):
        layer = IntegrationLayer()
        layer.initialize(tool_executor=fake_executor_ok)
        assert layer.is_initialized

    @pytest.mark.asyncio
    async def test_execute_chain(self):
        layer = IntegrationLayer()
        layer.initialize(tool_executor=fake_executor_ok)

        chain = ToolChain(name="test").add_step("t1").add_step("t2")
        layer.register_chain(chain)

        result = await layer.execute_chain("test")
        assert result.status == ChainStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_execute_chain_not_found(self):
        layer = IntegrationLayer()
        layer.initialize(tool_executor=fake_executor_ok)

        result = await layer.execute_chain("nonexistent")
        assert result.status == ChainStatus.FAILED

    @pytest.mark.asyncio
    async def test_auto_route(self):
        layer = IntegrationLayer()
        layer.initialize(tool_executor=fake_executor_ok)

        result = await layer.auto_route("исследуй тренды AI")
        assert result is not None
        assert result.status == ChainStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_auto_route_no_match(self):
        layer = IntegrationLayer()
        layer.initialize(tool_executor=fake_executor_ok)

        result = await layer.auto_route("random text 12345")
        assert result is None

    @pytest.mark.asyncio
    async def test_execute_safe(self):
        layer = IntegrationLayer()
        layer.initialize(tool_executor=fake_executor_ok)

        result = await layer.execute_safe("web_search", {"query": "test"})
        assert result.success

    @pytest.mark.asyncio
    async def test_execute_safe_fail(self):
        layer = IntegrationLayer()
        layer.initialize(tool_executor=fake_executor_fail)
        layer._retry_policy = RetryPolicy(max_retries=0)
        layer._executor._default_retry = RetryPolicy(max_retries=0)

        result = await layer.execute_safe("bad_tool", {})
        assert not result.success

    @pytest.mark.asyncio
    async def test_execute_parallel(self):
        layer = IntegrationLayer()
        layer.initialize(tool_executor=fake_executor_ok)

        results = await layer.execute_parallel([
            ("t1", {"a": 1}),
            ("t2", {"b": 2}),
            ("t3", {"c": 3}),
        ])
        assert len(results) == 3
        assert all(r.success for r in results)

    def test_create_chain(self):
        layer = IntegrationLayer()
        chain = layer.create_chain("custom", "My chain")
        assert chain.name == "custom"
        assert isinstance(chain, ToolChain)

    def test_get_health_report(self):
        layer = IntegrationLayer()
        layer.initialize(tool_executor=fake_executor_ok)
        report = layer.get_health_report()
        assert "monitor" in report
        assert "unhealthy_tools" in report

    def test_get_stats(self):
        layer = IntegrationLayer()
        stats = layer.get_stats()
        assert "initialized" in stats
        assert "health" in stats
        assert "router" in stats
        assert "fallbacks" in stats
        assert "executor" in stats
        assert "healer" in stats


# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCE
# ═══════════════════════════════════════════════════════════════════════════════


class TestGlobalInstance:
    """Тест глобального экземпляра."""

    def test_global_exists(self):
        assert integration_layer is not None
        assert isinstance(integration_layer, IntegrationLayer)
