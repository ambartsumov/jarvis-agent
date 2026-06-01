"""
Тесты для Parallel Execution Engine.
=======================================
Покрывает: ConcurrencyManager, ParallelDAGExecutor,
ParallelHypothesisChecker, TaskBatchQueue, ParallelEngine.
"""

import asyncio

import pytest

# Import DAGPlan for integration tests
from pds_ultimate.core.cognitive_engine import DAGPlan, NodeStatus
from pds_ultimate.core.parallel_engine import (
    ConcurrencyManager,
    ExecutionStats,
    Hypothesis,
    HypothesisStatus,
    ParallelDAGExecutor,
    ParallelEngine,
    ParallelHypothesisChecker,
    ParallelResult,
    TaskBatchQueue,
    parallel_engine,
)

# ═══════════════════════════════════════════════════════════════════════════════
# HYPOTHESIS
# ═══════════════════════════════════════════════════════════════════════════════


class TestHypothesis:
    def test_creation(self):
        h = Hypothesis(id="h1", statement="Earth is round")
        assert h.status == HypothesisStatus.PENDING
        assert h.confidence == 0.0
        assert h.is_checked is False

    def test_is_checked_confirmed(self):
        h = Hypothesis(id="h1", statement="x",
                       status=HypothesisStatus.CONFIRMED)
        assert h.is_checked is True

    def test_is_checked_pending(self):
        h = Hypothesis(id="h1", statement="x")
        assert h.is_checked is False

    def test_to_dict(self):
        h = Hypothesis(
            id="h1", statement="test",
            status=HypothesisStatus.CONFIRMED, confidence=0.95
        )
        d = h.to_dict()
        assert d["id"] == "h1"
        assert d["status"] == "confirmed"
        assert d["confidence"] == 0.95


class TestParallelResult:
    def test_success(self):
        r = ParallelResult(task_id="t1", success=True, result="ok")
        assert r.success is True

    def test_failure(self):
        r = ParallelResult(task_id="t1", success=False, error="fail")
        assert r.error == "fail"

    def test_to_dict(self):
        r = ParallelResult(task_id="t1", success=True, duration_ms=42.5)
        d = r.to_dict()
        assert d["task_id"] == "t1"
        assert d["duration_ms"] == 42.5


class TestExecutionStats:
    def test_to_dict(self):
        s = ExecutionStats(total_tasks=5, parallel_tasks=3)
        d = s.to_dict()
        assert d["total_tasks"] == 5
        assert d["parallel_tasks"] == 3


# ═══════════════════════════════════════════════════════════════════════════════
# CONCURRENCY MANAGER
# ═══════════════════════════════════════════════════════════════════════════════


class TestConcurrencyManager:
    @pytest.mark.asyncio
    async def test_acquire_release(self):
        cm = ConcurrencyManager(max_concurrent=3)
        await cm.acquire()
        assert cm.active_count == 1
        cm.release()
        assert cm.active_count == 0

    @pytest.mark.asyncio
    async def test_peak_count(self):
        cm = ConcurrencyManager(max_concurrent=5)
        await cm.acquire()
        await cm.acquire()
        assert cm.peak_count == 2
        cm.release()
        cm.release()
        assert cm.peak_count == 2  # Peak не уменьшается

    @pytest.mark.asyncio
    async def test_run_limited(self):
        cm = ConcurrencyManager(max_concurrent=3)

        async def task():
            return 42

        result = await cm.run_limited(task())
        assert result == 42

    @pytest.mark.asyncio
    async def test_category_llm(self):
        cm = ConcurrencyManager(max_llm_concurrent=2)
        await cm.acquire("llm")
        assert cm.active_count == 1
        cm.release("llm")

    @pytest.mark.asyncio
    async def test_category_browser(self):
        cm = ConcurrencyManager(max_browser_concurrent=2)
        await cm.acquire("browser")
        assert cm.active_count == 1
        cm.release("browser")


# ═══════════════════════════════════════════════════════════════════════════════
# PARALLEL DAG EXECUTOR
# ═══════════════════════════════════════════════════════════════════════════════


class TestParallelDAGExecutor:
    """Тесты параллельного DAG."""

    @pytest.mark.asyncio
    async def test_simple_dag(self):
        """Простой DAG: A → B."""
        plan = DAGPlan("test")
        plan.add_node("A", "Step A")
        plan.add_node("B", "Step B", depends_on=["A"])

        async def executor(node_id, tool_name, tool_params):
            return f"done_{node_id}"

        executor_obj = ParallelDAGExecutor()
        results = await executor_obj.execute_dag(plan, executor)

        assert len(results) == 2
        assert all(r.success for r in results)
        assert plan.is_complete

    @pytest.mark.asyncio
    async def test_parallel_nodes(self):
        """Параллельные узлы: A и B → C."""
        plan = DAGPlan("test")
        plan.add_node("A", "Step A")
        plan.add_node("B", "Step B")
        plan.add_node("C", "Step C", depends_on=["A", "B"])

        execution_order = []

        async def executor(node_id, tool_name, tool_params):
            execution_order.append(node_id)
            await asyncio.sleep(0.01)
            return f"done_{node_id}"

        executor_obj = ParallelDAGExecutor()
        results = await executor_obj.execute_dag(plan, executor)

        assert len(results) == 3
        assert all(r.success for r in results)
        # C должен быть после A и B
        assert execution_order.index("C") > execution_order.index("A")
        assert execution_order.index("C") > execution_order.index("B")

    @pytest.mark.asyncio
    async def test_dag_with_failure(self):
        """Узел проваливается → зависимые пропускаются."""
        plan = DAGPlan("test")
        plan.add_node("A", "Step A", max_retries=0)
        plan.add_node("B", "Step B", depends_on=["A"])

        async def executor(node_id, tool_name, tool_params):
            if node_id == "A":
                raise ValueError("fail")
            return "ok"

        executor_obj = ParallelDAGExecutor()
        results = await executor_obj.execute_dag(plan, executor)

        a_result = [r for r in results if r.task_id == "A"][0]
        assert a_result.success is False
        assert plan.nodes["B"].status == NodeStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_single_node(self):
        plan = DAGPlan("test")
        plan.add_node("only", "Only step")

        async def executor(node_id, tool_name, tool_params):
            return "done"

        executor_obj = ParallelDAGExecutor()
        results = await executor_obj.execute_dag(plan, executor)
        assert len(results) == 1
        assert results[0].success

    @pytest.mark.asyncio
    async def test_empty_dag(self):
        plan = DAGPlan("test")

        async def executor(node_id, tool_name, tool_params):
            return "done"

        executor_obj = ParallelDAGExecutor()
        results = await executor_obj.execute_dag(plan, executor)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_stats_tracking(self):
        plan = DAGPlan("test")
        plan.add_node("A", "Step A")
        plan.add_node("B", "Step B")

        async def executor(node_id, tool_name, tool_params):
            return "done"

        executor_obj = ParallelDAGExecutor()
        await executor_obj.execute_dag(plan, executor)
        assert executor_obj.stats.total_tasks >= 2


# ═══════════════════════════════════════════════════════════════════════════════
# PARALLEL HYPOTHESIS CHECKER
# ═══════════════════════════════════════════════════════════════════════════════


class TestParallelHypothesisChecker:
    """Тесты параллельной проверки гипотез."""

    @pytest.mark.asyncio
    async def test_check_single(self):
        checker = ParallelHypothesisChecker()

        async def check(h):
            h.status = HypothesisStatus.CONFIRMED
            h.confidence = 0.9
            return h

        hypotheses = [Hypothesis(id="h1", statement="Earth is round")]
        results = await checker.check_hypotheses(hypotheses, check)

        assert len(results) == 1
        assert results[0].status == HypothesisStatus.CONFIRMED

    @pytest.mark.asyncio
    async def test_check_multiple_parallel(self):
        checker = ParallelHypothesisChecker()
        order = []

        async def check(h):
            order.append(h.id)
            await asyncio.sleep(0.01)
            h.status = HypothesisStatus.CONFIRMED
            h.confidence = 0.8
            return h

        hypotheses = [
            Hypothesis(id=f"h{i}", statement=f"Claim {i}")
            for i in range(5)
        ]
        results = await checker.check_hypotheses(hypotheses, check)

        assert len(results) == 5
        assert all(r.status == HypothesisStatus.CONFIRMED for r in results)

    @pytest.mark.asyncio
    async def test_check_with_error(self):
        checker = ParallelHypothesisChecker()

        async def check(h):
            if h.id == "h2":
                raise ValueError("check failed")
            h.status = HypothesisStatus.CONFIRMED
            return h

        hypotheses = [
            Hypothesis(id="h1", statement="ok"),
            Hypothesis(id="h2", statement="fail"),
        ]
        results = await checker.check_hypotheses(hypotheses, check)

        assert results[0].status == HypothesisStatus.CONFIRMED
        assert results[1].status == HypothesisStatus.ERROR

    @pytest.mark.asyncio
    async def test_empty_hypotheses(self):
        checker = ParallelHypothesisChecker()

        async def check(h):
            return h

        results = await checker.check_hypotheses([], check)
        assert results == []

    def test_generate_hypotheses(self):
        checker = ParallelHypothesisChecker()
        claims = ["Claim 1", "Claim 2", "Claim 3"]
        hypotheses = checker.generate_hypotheses(claims, sources=["src1"])
        assert len(hypotheses) == 3
        assert hypotheses[0].id == "h_1"
        assert hypotheses[0].statement == "Claim 1"
        assert hypotheses[0].sources == ["src1"]

    def test_summarize_results(self):
        checker = ParallelHypothesisChecker()
        hypotheses = [
            Hypothesis(id="h1", statement="A",
                       status=HypothesisStatus.CONFIRMED, confidence=0.9),
            Hypothesis(id="h2", statement="B",
                       status=HypothesisStatus.REFUTED, confidence=0.3),
            Hypothesis(id="h3", statement="C",
                       status=HypothesisStatus.UNCERTAIN, confidence=0.5),
        ]
        summary = checker.summarize_results(hypotheses)
        assert summary["total"] == 3
        assert summary["confirmed"] == 1
        assert summary["refuted"] == 1
        assert summary["uncertain"] == 1

    @pytest.mark.asyncio
    async def test_checked_count(self):
        checker = ParallelHypothesisChecker()

        async def check(h):
            h.status = HypothesisStatus.CONFIRMED
            return h

        await checker.check_hypotheses(
            [Hypothesis(id="h1", statement="x")], check
        )
        assert checker.checked_count == 1


# ═══════════════════════════════════════════════════════════════════════════════
# TASK BATCH QUEUE
# ═══════════════════════════════════════════════════════════════════════════════


async def _async_value(val):
    """Helper: async function returning a value."""
    return val


class TestTaskBatchQueue:
    @pytest.mark.asyncio
    async def test_submit_and_execute(self):
        queue = TaskBatchQueue(max_batch_size=2, flush_interval_ms=50)
        await queue.start()

        try:
            result = await queue.submit(
                "t1", "translate",
                lambda: _async_value("translated"),
            )
            assert result == "translated"
        finally:
            await queue.stop()

    @pytest.mark.asyncio
    async def test_queue_sizes(self):
        queue = TaskBatchQueue()
        assert queue.queue_sizes == {}

    def test_stats(self):
        queue = TaskBatchQueue()
        s = queue.stats
        assert s.total_tasks == 0

    @pytest.mark.asyncio
    async def test_start_stop(self):
        queue = TaskBatchQueue()
        await queue.start()
        await queue.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# PARALLEL ENGINE (orchestrator)
# ═══════════════════════════════════════════════════════════════════════════════


class TestParallelEngine:
    @pytest.mark.asyncio
    async def test_run_parallel(self):
        engine = ParallelEngine()
        tasks = {
            "t1": lambda: _async_value("a"),
            "t2": lambda: _async_value("b"),
        }
        results = await engine.run_parallel(tasks)
        assert len(results) == 2
        assert results["t1"].success
        assert results["t2"].success

    @pytest.mark.asyncio
    async def test_run_parallel_empty(self):
        engine = ParallelEngine()
        results = await engine.run_parallel({})
        assert results == {}

    @pytest.mark.asyncio
    async def test_run_parallel_with_error(self):
        engine = ParallelEngine()

        async def failing():
            raise ValueError("boom")

        tasks = {
            "ok": lambda: _async_value("good"),
            "fail": failing,
        }
        results = await engine.run_parallel(tasks)
        assert results["ok"].success is True
        assert results["fail"].success is False
        assert "boom" in results["fail"].error

    @pytest.mark.asyncio
    async def test_start_stop(self):
        engine = ParallelEngine()
        await engine.start()
        await engine.stop()

    def test_get_stats(self):
        engine = ParallelEngine()
        stats = engine.get_stats()
        assert "concurrency" in stats
        assert "dag" in stats
        assert "hypothesis" in stats
        assert "batch" in stats

    def test_properties(self):
        engine = ParallelEngine()
        assert isinstance(engine.concurrency, ConcurrencyManager)
        assert isinstance(engine.dag_executor, ParallelDAGExecutor)
        assert isinstance(engine.hypothesis_checker, ParallelHypothesisChecker)
        assert isinstance(engine.batch_queue, TaskBatchQueue)


# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCE
# ═══════════════════════════════════════════════════════════════════════════════


class TestGlobalParallelEngine:
    def test_exists(self):
        assert parallel_engine is not None
        assert isinstance(parallel_engine, ParallelEngine)
