"""
Tests for Agent v6 — DAG Planner + Sub-Agents + KV-Cache
=========================================================
Step 3: Comprehensive test suite.

Tests:
- core/planner.py (TaskPlanner, ExecutionPlan, PlanNode)
- core/sub_agents.py (SubAgent, SubAgentPool, SelfAttentionScorer, ResultAggregator)
- core/kv_cache.py (KVCache, PagedAttentionManager, QuantizedCache, SemanticDedup, ContextOptimizer)
- core/agent.py v6 (3-mode dispatch, planned execution, caching)
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pds_ultimate.core.agent import (
    Agent,
    AgentAction,
    AgentResponse,
    AgentStep,
    TaskVerifier,
    _sanitize_answer,
    agent,
    get_agent,
)
from pds_ultimate.core.kv_cache import (
    ContextOptimizer,
    KVCache,
    PagedAttentionManager,
    QuantizedCache,
    SemanticDedup,
    estimate_tokens,
)

# ════════════════════════════════════════════════════════════════════════════
# PART 1: Planner Tests
# ════════════════════════════════════════════════════════════════════════════
from pds_ultimate.core.planner import (
    ExecutionPlan,
    NodeStatus,
    PlanComplexity,
    PlanNode,
    TaskPlanner,
)
from pds_ultimate.core.sub_agents import (
    ResultAggregator,
    SelfAttentionScorer,
    SubAgent,
    SubAgentPool,
    SubAgentResult,
    SubAgentStatus,
)


class TestPlanNode:
    """Tests for PlanNode dataclass."""

    def test_create_node(self):
        node = PlanNode(id="step_1", description="Test step")
        assert node.id == "step_1"
        assert node.status == NodeStatus.PENDING
        assert node.result is None
        assert node.error is None
        assert node.retry_count == 0

    def test_mark_running(self):
        node = PlanNode(id="s1", description="test")
        node.mark_running()
        assert node.status == NodeStatus.RUNNING
        assert node.started_at is not None

    def test_mark_completed(self):
        node = PlanNode(id="s1", description="test")
        node.mark_running()
        time.sleep(0.01)
        node.mark_completed("done")
        assert node.status == NodeStatus.COMPLETED
        assert node.result == "done"
        assert node.completed_at is not None
        assert node.duration_ms > 0

    def test_mark_failed(self):
        node = PlanNode(id="s1", description="test")
        node.mark_running()
        node.mark_failed("error!")
        assert node.status == NodeStatus.FAILED
        assert node.error == "error!"

    def test_is_terminal(self):
        node = PlanNode(id="s1", description="test")
        assert not node.is_terminal
        node.mark_running()
        assert not node.is_terminal
        node.mark_completed("ok")
        assert node.is_terminal

    def test_can_retry(self):
        node = PlanNode(id="s1", description="test", max_retries=2)
        assert node.can_retry()
        node.retry_count = 2
        assert not node.can_retry()

    def test_to_dict(self):
        node = PlanNode(id="s1", description="Test", tool_name="search")
        d = node.to_dict()
        assert d["id"] == "s1"
        assert d["tool"] == "search"
        assert d["status"] == "pending"

    def test_duration_ms_no_timing(self):
        node = PlanNode(id="s1", description="test")
        assert node.duration_ms == 0


class TestExecutionPlan:
    """Tests for ExecutionPlan (DAG)."""

    def _make_plan(self) -> ExecutionPlan:
        plan = ExecutionPlan(goal="Test goal")
        plan.add_node(PlanNode(id="a", description="Step A"))
        plan.add_node(PlanNode(id="b", description="Step B", depends_on=["a"]))
        plan.add_node(PlanNode(id="c", description="Step C", depends_on=["a"]))
        plan.add_node(
            PlanNode(id="d", description="Step D", depends_on=["b", "c"]))
        return plan

    def test_add_node(self):
        plan = ExecutionPlan(goal="test")
        plan.add_node(PlanNode(id="x", description="X"))
        assert "x" in plan.nodes

    def test_get_ready_nodes_initial(self):
        plan = self._make_plan()
        ready = plan.get_ready_nodes()
        assert len(ready) == 1
        assert ready[0].id == "a"

    def test_get_ready_nodes_after_completion(self):
        plan = self._make_plan()
        plan.nodes["a"].mark_completed("done")
        ready = plan.get_ready_nodes()
        ids = {n.id for n in ready}
        assert ids == {"b", "c"}

    def test_get_ready_nodes_all_deps(self):
        plan = self._make_plan()
        plan.nodes["a"].mark_completed("done")
        plan.nodes["b"].mark_completed("done")
        plan.nodes["c"].mark_completed("done")
        ready = plan.get_ready_nodes()
        assert len(ready) == 1
        assert ready[0].id == "d"

    def test_is_done(self):
        plan = self._make_plan()
        assert not plan.is_done
        for n in plan.nodes.values():
            n.mark_completed("ok")
        assert plan.is_done

    def test_has_failures(self):
        plan = self._make_plan()
        assert not plan.has_failures
        plan.nodes["a"].mark_failed("err")
        assert plan.has_failures

    def test_get_completed_results(self):
        plan = self._make_plan()
        plan.nodes["a"].mark_completed("result_a")
        results = plan.get_completed_results()
        assert results == {"a": "result_a"}

    def test_get_progress(self):
        plan = self._make_plan()
        plan.nodes["a"].mark_completed("ok")
        plan.nodes["b"].mark_failed("err")
        progress = plan.get_progress()
        assert progress["total"] == 4
        assert progress["completed"] == 1
        assert progress["failed"] == 1
        assert progress["pending"] == 2
        assert progress["progress_pct"] == 25

    def test_validate_dag_valid(self):
        plan = self._make_plan()
        errors = plan.validate_dag()
        assert errors == []

    def test_validate_dag_missing_dep(self):
        plan = ExecutionPlan(goal="test")
        plan.add_node(
            PlanNode(id="a", description="A", depends_on=["missing"]))
        errors = plan.validate_dag()
        assert len(errors) == 1
        assert "missing" in errors[0]

    def test_validate_dag_cycle(self):
        plan = ExecutionPlan(goal="test")
        plan.add_node(PlanNode(id="a", description="A", depends_on=["b"]))
        plan.add_node(PlanNode(id="b", description="B", depends_on=["a"]))
        errors = plan.validate_dag()
        assert any("cycle" in e.lower() for e in errors)

    def test_to_dict(self):
        plan = self._make_plan()
        d = plan.to_dict()
        assert d["goal"] == "Test goal"
        assert "progress" in d
        assert "nodes" in d
        assert len(d["nodes"]) == 4

    def test_get_failed_nodes(self):
        plan = self._make_plan()
        plan.nodes["b"].mark_failed("err")
        failed = plan.get_failed_nodes()
        assert len(failed) == 1
        assert failed[0].id == "b"


class TestTaskPlanner:
    """Tests for TaskPlanner complexity classification and planning."""

    def setup_method(self):
        self.planner = TaskPlanner()

    def test_classify_simple_short(self):
        assert self.planner.classify_complexity(
            "привет") == PlanComplexity.SIMPLE

    def test_classify_simple_greeting(self):
        assert self.planner.classify_complexity(
            "как дела") == PlanComplexity.SIMPLE

    def test_classify_complex_keywords(self):
        msg = "Проанализируй мои продажи за месяц, сравни с прошлым, создай отчёт подробно по шагам"
        assert self.planner.classify_complexity(msg) == PlanComplexity.COMPLEX

    def test_classify_moderate_single_keyword(self):
        msg = (
            "Найди информацию по этому вопросу и расскажи подробно, "
            "мне нужен детальный анализ этой проблемы"
        )
        result = self.planner.classify_complexity(msg)
        assert result in (PlanComplexity.MODERATE, PlanComplexity.COMPLEX)

    def test_classify_moderate_questions(self):
        msg = "Что это? Как работает? Зачем нужно?"
        result = self.planner.classify_complexity(msg)
        assert result in (PlanComplexity.MODERATE, PlanComplexity.COMPLEX)

    @pytest.mark.asyncio
    async def test_create_plan_success(self):
        """Test plan creation with mocked LLM."""
        mock_plan = json.dumps({
            "steps": [
                {"id": "step_1", "description": "Search", "tool": "web_search",
                    "params": {"query": "test"}, "depends_on": []},
                {"id": "synthesize", "description": "Summarize",
                    "tool": None, "params": {}, "depends_on": ["step_1"]},
            ]
        })

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=mock_plan)
        with patch("pds_ultimate.core.llm_engine.llm_engine", mock_llm):
            plan = await self.planner.create_plan(
                goal="Find info",
                tools_description="web_search: search the web",
            )

        assert len(plan.nodes) == 2
        assert "step_1" in plan.nodes
        assert "synthesize" in plan.nodes
        assert plan.nodes["synthesize"].depends_on == ["step_1"]

    @pytest.mark.asyncio
    async def test_create_plan_auto_synthesize(self):
        """Test that synthesize step is auto-added."""
        mock_plan = json.dumps({
            "steps": [
                {"id": "step_1", "description": "Do thing", "depends_on": []},
            ]
        })

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=mock_plan)
        with patch("pds_ultimate.core.llm_engine.llm_engine", mock_llm):
            plan = await self.planner.create_plan(
                goal="Do thing",
                tools_description="none",
            )

        assert "synthesize" in plan.nodes

    @pytest.mark.asyncio
    async def test_create_plan_fallback_on_error(self):
        """Test fallback plan on LLM failure."""
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(side_effect=Exception("API error"))
        with patch("pds_ultimate.core.llm_engine.llm_engine", mock_llm):
            plan = await self.planner.create_plan(
                goal="Test",
                tools_description="none",
            )

        assert len(plan.nodes) == 1
        assert "direct" in plan.nodes

    @pytest.mark.asyncio
    async def test_create_plan_validates_dag(self):
        """Test that invalid deps are auto-cleaned."""
        mock_plan = json.dumps({
            "steps": [
                {"id": "s1", "description": "Do",
                    "depends_on": ["nonexistent"]},
            ]
        })

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=mock_plan)
        with patch("pds_ultimate.core.llm_engine.llm_engine", mock_llm):
            plan = await self.planner.create_plan(
                goal="Test",
                tools_description="none",
            )

        # Invalid dep should be removed
        s1_deps = plan.nodes["s1"].depends_on
        assert "nonexistent" not in s1_deps

    @pytest.mark.asyncio
    async def test_replan(self):
        """Test replanning after failure."""
        # Original plan
        original = ExecutionPlan(goal="Goal")
        node_a = PlanNode(id="a", description="Step A")
        node_a.mark_completed("result_a")
        original.add_node(node_a)
        failed_node = PlanNode(id="b", description="Step B")
        failed_node.mark_failed("timeout")
        original.add_node(failed_node)

        mock_plan = json.dumps({
            "steps": [
                {"id": "b_retry", "description": "Retry B differently", "depends_on": []},
            ]
        })

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=mock_plan)
        with patch("pds_ultimate.core.llm_engine.llm_engine", mock_llm):
            new_plan = await self.planner.replan(
                original_plan=original,
                failed_node=failed_node,
                tools_description="none",
            )

        assert new_plan.revision == 1
        # Carried-over completed result
        assert "a" in new_plan.nodes
        assert new_plan.nodes["a"].status == NodeStatus.COMPLETED

    def test_parse_plan_max_steps(self):
        """Test that max_steps limits the plan size."""
        plan_data = {
            "steps": [
                {"id": f"s{i}", "description": f"Step {i}"}
                for i in range(20)
            ]
        }
        plan = self.planner._parse_plan("goal", plan_data, max_steps=3)
        # 3 steps + auto-synthesize = 4
        assert len(plan.nodes) <= 5

    def test_fallback_plan(self):
        plan = self.planner._fallback_plan("test goal")
        assert len(plan.nodes) == 1
        assert "direct" in plan.nodes


# ════════════════════════════════════════════════════════════════════════════
# PART 2: Sub-Agents Tests
# ════════════════════════════════════════════════════════════════════════════


class TestSelfAttentionScorer:
    """Tests for the self-attention relevance scorer."""

    def test_empty_result(self):
        assert SelfAttentionScorer.score("goal", "") == 0.0

    def test_empty_whitespace(self):
        assert SelfAttentionScorer.score("goal", "   ") == 0.0

    def test_perfect_overlap(self):
        score = SelfAttentionScorer.score(
            "find weather in Moscow",
            "The weather in Moscow is sunny today",
        )
        assert score > 0.3

    def test_no_overlap(self):
        score = SelfAttentionScorer.score(
            "find weather",
            "абсолютно несвязанный текст про кулинарию и рецепты",
        )
        assert score < 0.5

    def test_error_penalty(self):
        score_ok = SelfAttentionScorer.score(
            "find data results", "Here is the result with all the data you requested")
        score_err = SelfAttentionScorer.score(
            "find data results", "Error: connection failed with traceback exception")
        assert score_err <= score_ok

    def test_short_penalty(self):
        score_short = SelfAttentionScorer.score("long detailed goal", "ok")
        score_long = SelfAttentionScorer.score(
            "long detailed goal",
            "Here is a comprehensive answer to your long detailed goal with analysis",
        )
        assert score_long > score_short

    def test_score_range(self):
        score = SelfAttentionScorer.score("test", "test result")
        assert 0.0 <= score <= 1.0


class TestSubAgentResult:
    """Tests for SubAgentResult dataclass."""

    def test_create(self):
        r = SubAgentResult(
            node_id="s1",
            status=SubAgentStatus.COMPLETED,
            output="result",
            relevance_score=0.8,
        )
        assert r.node_id == "s1"
        assert r.output == "result"
        assert r.relevance_score == 0.8

    def test_failed(self):
        r = SubAgentResult(
            node_id="s1",
            status=SubAgentStatus.FAILED,
            error="timeout",
        )
        assert r.status == SubAgentStatus.FAILED
        assert r.error == "timeout"


class TestResultAggregator:
    """Tests for the result aggregation logic."""

    def test_aggregate_empty(self):
        result = ResultAggregator.aggregate([], "goal")
        assert result["stats"]["total"] == 0
        assert result["best_result"] is None

    def test_aggregate_successful(self):
        results = [
            SubAgentResult("s1", SubAgentStatus.COMPLETED,
                           "result 1", relevance_score=0.9),
            SubAgentResult("s2", SubAgentStatus.COMPLETED,
                           "result 2", relevance_score=0.5),
        ]
        agg = ResultAggregator.aggregate(results, "goal")
        assert agg["stats"]["successful"] == 2
        assert agg["stats"]["failed"] == 0
        assert agg["best_result"].node_id == "s1"  # highest relevance
        assert "result 1" in agg["merged_context"]

    def test_aggregate_mixed(self):
        results = [
            SubAgentResult("s1", SubAgentStatus.COMPLETED,
                           "ok", relevance_score=0.8),
            SubAgentResult("s2", SubAgentStatus.FAILED, error="err"),
        ]
        agg = ResultAggregator.aggregate(results, "goal")
        assert agg["stats"]["successful"] == 1
        assert agg["stats"]["failed"] == 1
        assert len(agg["failed"]) == 1

    def test_aggregate_sort_by_relevance(self):
        results = [
            SubAgentResult("low", SubAgentStatus.COMPLETED,
                           "low", relevance_score=0.1),
            SubAgentResult("high", SubAgentStatus.COMPLETED,
                           "high", relevance_score=0.9),
            SubAgentResult("mid", SubAgentStatus.COMPLETED,
                           "mid", relevance_score=0.5),
        ]
        agg = ResultAggregator.aggregate(results, "goal")
        assert agg["best_result"].node_id == "high"


class TestSubAgent:
    """Tests for SubAgent execution."""

    @pytest.mark.asyncio
    async def test_execute_with_tool(self):
        """Test sub-agent execution with a tool."""
        node = PlanNode(
            id="s1",
            description="Search for info",
            tool_name="test_tool",
            tool_params={"query": "test"},
        )

        mock_reg = MagicMock()
        mock_reg.has_tool.return_value = True
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = "Tool result data"
        mock_result.data = None
        mock_reg.execute = AsyncMock(return_value=mock_result)

        with patch("pds_ultimate.core.tools.tool_registry", mock_reg):
            sa = SubAgent(node=node, goal="Find info")
            result = await sa.execute()

        assert result.status == SubAgentStatus.COMPLETED
        assert "Tool result data" in result.output
        assert result.tool_calls == 1
        assert result.relevance_score > 0

    @pytest.mark.asyncio
    async def test_execute_with_llm(self):
        """Test sub-agent execution without tool (LLM reasoning)."""
        node = PlanNode(id="s1", description="Think about this")

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="Thoughtful answer")
        with patch("pds_ultimate.core.llm_engine.llm_engine", mock_llm):
            sa = SubAgent(node=node, goal="Analyze something")
            result = await sa.execute()

        assert result.status == SubAgentStatus.COMPLETED
        assert result.output == "Thoughtful answer"
        assert result.tool_calls == 0

    @pytest.mark.asyncio
    async def test_execute_tool_failure(self):
        """Test sub-agent handles tool failure."""
        node = PlanNode(
            id="s1",
            description="Do thing",
            tool_name="bad_tool",
            tool_params={},
        )

        mock_reg = MagicMock()
        mock_reg.has_tool.return_value = True
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "Connection timeout"
        mock_reg.execute = AsyncMock(return_value=mock_result)

        with patch("pds_ultimate.core.tools.tool_registry", mock_reg):
            sa = SubAgent(node=node, goal="Do thing")
            result = await sa.execute()

        assert result.status == SubAgentStatus.FAILED
        assert "timeout" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_with_deps_context(self):
        """Test that completed results are passed as context."""
        node = PlanNode(id="s2", description="Use previous results")
        completed = {"s1": "Previous result data"}

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="Combined answer")
        with patch("pds_ultimate.core.llm_engine.llm_engine", mock_llm):
            sa = SubAgent(
                node=node,
                goal="Combine results",
                completed_results=completed,
            )
            result = await sa.execute()

        # Verify the prompt included the completed results
        call_args = mock_llm.chat.call_args
        assert "Previous result data" in call_args.kwargs.get("message", "")


class TestSubAgentPool:
    """Tests for SubAgentPool orchestration."""

    @pytest.mark.asyncio
    async def test_execute_parallel_empty(self):
        pool = SubAgentPool()
        results = await pool.execute_parallel([], "goal")
        assert results == []

    @pytest.mark.asyncio
    async def test_execute_parallel_single(self):
        node = PlanNode(id="s1", description="Test")

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="Result")
        with patch("pds_ultimate.core.llm_engine.llm_engine", mock_llm):
            pool = SubAgentPool(max_concurrent=4, timeout=30)
            results = await pool.execute_parallel([node], "goal")

        assert len(results) == 1
        assert results[0].status == SubAgentStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_execute_parallel_multiple(self):
        nodes = [
            PlanNode(id=f"s{i}", description=f"Step {i}")
            for i in range(3)
        ]

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="Result")
        with patch("pds_ultimate.core.llm_engine.llm_engine", mock_llm):
            pool = SubAgentPool(max_concurrent=4, timeout=30)
            results = await pool.execute_parallel(nodes, "goal")

        assert len(results) == 3
        completed = [r for r in results if r.status ==
                     SubAgentStatus.COMPLETED]
        assert len(completed) == 3

    @pytest.mark.asyncio
    async def test_execute_parallel_with_timeout(self):
        """Test timeout handling."""
        node = PlanNode(id="slow", description="Slow task")

        async def slow_chat(*args, **kwargs):
            await asyncio.sleep(5)
            return "Never reached"

        mock_llm = MagicMock()
        mock_llm.chat = slow_chat
        with patch("pds_ultimate.core.llm_engine.llm_engine", mock_llm):
            pool = SubAgentPool(max_concurrent=2, timeout=0.1, max_retries=0)
            results = await pool.execute_parallel([node], "goal")

        assert len(results) == 1
        assert results[0].status == SubAgentStatus.FAILED
        assert "timeout" in results[0].error.lower()

    @pytest.mark.asyncio
    async def test_total_executed_counter(self):
        pool = SubAgentPool(max_concurrent=2, timeout=10)
        node = PlanNode(id="s1", description="Test")

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="OK")
        with patch("pds_ultimate.core.llm_engine.llm_engine", mock_llm):
            await pool.execute_parallel([node], "goal")

        assert pool.total_executed >= 1


# ════════════════════════════════════════════════════════════════════════════
# PART 3: KV-Cache Tests
# ════════════════════════════════════════════════════════════════════════════


class TestEstimateTokens:
    def test_empty(self):
        assert estimate_tokens("") == 0

    def test_short(self):
        assert estimate_tokens("hello") >= 1

    def test_long(self):
        text = "a" * 3500
        tokens = estimate_tokens(text)
        assert 900 < tokens < 1100  # ~1000 tokens


class TestKVCache:
    """Tests for the prompt-response cache."""

    def test_put_and_get(self):
        cache = KVCache(max_size=10)
        key = cache.make_key("prompt1")
        cache.put(key, "response1")

        entry = cache.get(key)
        assert entry is not None
        assert entry.response == "response1"

    def test_cache_miss(self):
        cache = KVCache()
        assert cache.get("nonexistent") is None

    def test_lru_eviction(self):
        cache = KVCache(max_size=2)
        k1 = cache.make_key("p1")
        k2 = cache.make_key("p2")
        k3 = cache.make_key("p3")

        cache.put(k1, "response_one")
        cache.put(k2, "response_two")
        cache.put(k3, "response_three")  # Should evict k1

        assert cache.get(k1) is None
        assert cache.get(k2) is not None
        assert cache.get(k3) is not None

    def test_ttl_expiration(self):
        cache = KVCache(ttl=0)  # Immediate expiration
        key = cache.make_key("test")
        cache.put(key, "response")
        time.sleep(0.01)
        assert cache.get(key) is None

    def test_hit_rate(self):
        cache = KVCache()
        key = cache.make_key("test")
        cache.put(key, "response")

        cache.get(key)  # hit
        cache.get(key)  # hit
        cache.get("miss")  # miss

        stats = cache.stats
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["hit_rate"] > 60

    def test_invalidate(self):
        cache = KVCache()
        key = cache.make_key("test")
        cache.put(key, "response")
        assert cache.invalidate(key)
        assert cache.get(key) is None

    def test_invalidate_nonexistent(self):
        cache = KVCache()
        assert not cache.invalidate("nope")

    def test_clear(self):
        cache = KVCache()
        cache.put(cache.make_key("a"), "a")
        cache.put(cache.make_key("b"), "b")
        cache.clear()
        assert cache.stats["size"] == 0

    def test_dont_cache_short(self):
        cache = KVCache()
        key = cache.make_key("test")
        cache.put(key, "hi")  # Too short (< 5 chars)
        assert cache.get(key) is None

    def test_prune_expired(self):
        cache = KVCache(ttl=0)
        cache.put(cache.make_key("a"), "response_a")
        time.sleep(0.01)
        removed = cache.prune_expired()
        assert removed == 1

    def test_make_key_deterministic(self):
        cache = KVCache()
        k1 = cache.make_key("a", "b")
        k2 = cache.make_key("a", "b")
        assert k1 == k2

    def test_make_key_different(self):
        cache = KVCache()
        k1 = cache.make_key("a")
        k2 = cache.make_key("b")
        assert k1 != k2


class TestPagedAttentionManager:
    """Tests for the paged context manager."""

    def test_add_content(self):
        pam = PagedAttentionManager(page_size=50)
        ids = pam.add_content("Hello world this is a test")
        assert len(ids) >= 1
        assert pam.page_count >= 1

    def test_add_empty(self):
        pam = PagedAttentionManager()
        ids = pam.add_content("")
        assert ids == []

    def test_get_context(self):
        pam = PagedAttentionManager(page_size=100)
        pam.add_content("The weather in Moscow is sunny", source="weather")
        pam.add_content("Python programming tutorial", source="tech")

        context = pam.get_context("weather Moscow", token_budget=500)
        assert len(context) > 0

    def test_get_context_empty(self):
        pam = PagedAttentionManager()
        assert pam.get_context("query") == ""

    def test_token_budget(self):
        pam = PagedAttentionManager(page_size=50)
        # Add lots of content
        for i in range(20):
            pam.add_content(f"This is page {i} with some content " * 10)

        context = pam.get_context("page 5", token_budget=100)
        tokens = estimate_tokens(context)
        assert tokens <= 150  # Some slack

    def test_relevance_scoring(self):
        pam = PagedAttentionManager(page_size=200)
        pam.add_content("Weather forecast for today is rain", relevance=0.9)
        pam.add_content("Cooking recipe for pasta carbonara", relevance=0.1)

        context = pam.get_context("weather forecast", token_budget=200)
        # Weather content should appear (higher relevance + keyword match)
        assert "weather" in context.lower() or "rain" in context.lower()

    def test_max_pages_eviction(self):
        pam = PagedAttentionManager(page_size=50, max_pages=3)
        for i in range(10):
            pam.add_content(f"Content block {i} with words " * 5)

        assert pam.page_count <= 3

    def test_clear(self):
        pam = PagedAttentionManager()
        pam.add_content("test content")
        pam.clear()
        assert pam.page_count == 0

    def test_stats(self):
        pam = PagedAttentionManager(page_size=100, max_pages=50)
        pam.add_content("Hello world")
        stats = pam.stats
        assert stats["page_count"] >= 1
        assert stats["max_pages"] == 50
        assert stats["total_tokens"] > 0


class TestQuantizedCache:
    """Tests for the quantized value cache."""

    def test_put_and_get(self):
        qc = QuantizedCache()
        qc.put("key1", "Hello world")
        assert qc.get("key1") == "Hello world"

    def test_get_nonexistent(self):
        qc = QuantizedCache()
        assert qc.get("nope") is None

    def test_has(self):
        qc = QuantizedCache()
        qc.put("key1", "value")
        assert qc.has("key1")
        assert not qc.has("key2")

    def test_remove(self):
        qc = QuantizedCache()
        qc.put("key1", "value")
        assert qc.remove("key1")
        assert not qc.has("key1")

    def test_lru_eviction(self):
        qc = QuantizedCache(max_entries=2)
        qc.put("a", "value_a")
        qc.put("b", "value_b")
        qc.put("c", "value_c")  # Evicts "a"
        assert qc.get("a") is None
        assert qc.get("b") is not None

    def test_unicode(self):
        qc = QuantizedCache()
        qc.put("ru", "Привет мир! 🌍")
        assert qc.get("ru") == "Привет мир! 🌍"

    def test_empty_value(self):
        qc = QuantizedCache()
        qc.put("empty", "")
        assert qc.get("empty") is None  # Empty not stored

    def test_stats(self):
        qc = QuantizedCache()
        qc.put("k1", "Hello world")
        stats = qc.stats
        assert stats["entries"] == 1
        assert stats["total_original_bytes"] > 0


class TestSemanticDedup:
    """Tests for semantic deduplication."""

    def test_exact_duplicates(self):
        dedup = SemanticDedup()
        segments = ["Hello world", "Hello world", "Different text"]
        result = dedup.deduplicate(segments)
        assert len(result) == 2

    def test_near_duplicates(self):
        dedup = SemanticDedup(similarity_threshold=0.8)
        segments = [
            "The weather in Moscow is sunny today",
            "The weather in Moscow is sunny today!",
            "Python programming is fun",
        ]
        result = dedup.deduplicate(segments)
        # Near-duplicate should be detected
        assert len(result) <= 2

    def test_no_duplicates(self):
        dedup = SemanticDedup()
        segments = ["Alpha", "Beta", "Gamma"]
        result = dedup.deduplicate(segments)
        assert len(result) == 3

    def test_empty_segments(self):
        dedup = SemanticDedup()
        result = dedup.deduplicate(["", "  ", "Valid"])
        assert len(result) == 1

    def test_single_segment(self):
        dedup = SemanticDedup()
        result = dedup.deduplicate(["Only one"])
        assert len(result) == 1

    def test_reset(self):
        dedup = SemanticDedup()
        dedup.deduplicate(["test"])
        dedup.reset()
        result = dedup.deduplicate(["test"])
        assert len(result) == 1  # Should work after reset

    def test_char_ngram_similarity(self):
        sim = SemanticDedup._char_ngram_similarity(
            "hello world", "hello world", n=3)
        assert sim == 1.0

    def test_char_ngram_no_similarity(self):
        sim = SemanticDedup._char_ngram_similarity("abc", "xyz", n=3)
        assert sim == 0.0


class TestContextOptimizer:
    """Tests for the unified context optimizer."""

    def test_init(self):
        opt = ContextOptimizer()
        assert opt.cache is not None
        assert opt.paged is not None
        assert opt.quantized is not None

    def test_add_and_get_context(self):
        opt = ContextOptimizer()
        opt.add_context("Weather information for today", source="weather")
        ctx = opt.get_optimized_context("weather", token_budget=500)
        assert "weather" in ctx.lower() or "Weather" in ctx

    def test_cache_response(self):
        opt = ContextOptimizer()
        opt.cache_response(["prompt1"], "response1")
        cached = opt.get_cached_response(["prompt1"])
        assert cached == "response1"

    def test_cache_miss(self):
        opt = ContextOptimizer()
        assert opt.get_cached_response(["nonexistent"]) is None

    def test_compressed_storage(self):
        opt = ContextOptimizer()
        opt.store_compressed("big_data", "A" * 10000)
        retrieved = opt.get_compressed("big_data")
        assert retrieved == "A" * 10000

    def test_clear_all(self):
        opt = ContextOptimizer()
        opt.add_context("test")
        opt.cache_response(["test"], "resp")
        opt.store_compressed("k", "v")
        opt.clear_all()
        assert opt.get_cached_response(["test"]) is None

    def test_stats(self):
        opt = ContextOptimizer()
        stats = opt.stats
        assert "cache" in stats
        assert "paged" in stats
        assert "quantized" in stats


# ════════════════════════════════════════════════════════════════════════════
# PART 4: Agent v6 Tests
# ════════════════════════════════════════════════════════════════════════════


class TestSanitizeAnswer:
    """Tests for the text sanitizer (unchanged from v5)."""

    def test_empty(self):
        assert _sanitize_answer("") == ""

    def test_normal_text(self):
        assert _sanitize_answer("Hello world") == "Hello world"

    def test_strip_think_tags(self):
        text = "<think>reasoning here</think>Final answer"
        assert _sanitize_answer(text) == "Final answer"

    def test_json_extraction(self):
        text = '{"answer": "The result is 42"}'
        assert _sanitize_answer(text) == "The result is 42"


class TestTaskVerifier:
    def test_fast_check_empty(self):
        assert TaskVerifier.fast_check("task", "") == 0.1

    def test_fast_check_normal(self):
        score = TaskVerifier.fast_check("What is 2+2?", "2+2 equals 4.")
        assert score >= 0.5

    def test_fast_check_json_leak(self):
        score = TaskVerifier.fast_check("test", '{"action": "test"}')
        assert score < 0.5

    def test_fast_check_hallucination(self):
        score = TaskVerifier.fast_check(
            "test", "as an ai language model, i cannot help with that")
        assert score < 0.5


class TestAgentV6:
    """Tests for Agent v6 three-mode dispatch."""

    def test_agent_init(self):
        a = Agent()
        assert a._planner is not None
        assert a._sub_pool is not None
        assert a._aggregator is not None
        assert a._optimizer is not None

    def test_select_mode_simple(self):
        a = Agent()
        mode = a._select_mode("привет")
        assert mode == "simple"

    def test_select_mode_tool_loop(self):
        a = Agent()
        mode = a._select_mode("покажи мой баланс")
        assert mode in ("simple", "tool_loop")

    def test_select_mode_planned(self):
        a = Agent()
        mode = a._select_mode(
            "Проанализируй все мои продажи за месяц, сравни с прошлым, "
            "создай отчёт по каждому клиенту и отправь на почту"
        )
        assert mode == "planned"

    def test_detect_oscillation_none(self):
        a = Agent()
        steps = [AgentStep(iteration=i) for i in range(2)]
        assert not a._detect_oscillation(steps)

    def test_detect_oscillation_detected(self):
        a = Agent()
        steps = []
        for i in range(4):
            action_type = "tool_call" if i % 2 == 0 else "final_answer"
            tool = "search" if i % 2 == 0 else None
            steps.append(AgentStep(
                iteration=i,
                action=AgentAction(
                    action_type=action_type,
                    tool_name=tool,
                ),
            ))
        assert a._detect_oscillation(steps)

    @pytest.mark.asyncio
    async def test_execute_simple_mode(self):
        """Test simple mode execution (direct LLM)."""
        a = Agent()

        with patch.object(a, "_select_mode", return_value="simple"), \
                patch("pds_ultimate.core.agent.memory_manager") as mock_mem, \
                patch("pds_ultimate.core.agent.llm_engine") as mock_llm:

            mock_mem.get_context.return_value = ""
            mock_llm.chat = AsyncMock(return_value="Привет! Как дела?")

            response = await a.execute("привет", chat_id=123)

        assert response.answer == "Привет! Как дела?"
        assert response.execution_mode == "simple"
        assert response.total_iterations == 1
        assert len(response.steps) == 1

    @pytest.mark.asyncio
    async def test_execute_simple_cached(self):
        """Test that cached responses are returned instantly."""
        a = Agent()

        # Pre-populate cache
        cache_key_parts = ["hello", "None"]
        a._optimizer.cache_response(cache_key_parts, "Cached response here")

        with patch.object(a, "_select_mode", return_value="simple"), \
                patch("pds_ultimate.core.agent.memory_manager") as mock_mem:

            mock_mem.get_context.return_value = ""

            response = await a.execute("hello", chat_id=None)

        assert response.answer == "Cached response here"
        assert response.execution_mode == "simple_cached"

        # Cleanup
        a._optimizer.clear_all()

    @pytest.mark.asyncio
    async def test_execute_tool_loop_mode(self):
        """Test tool_loop mode (v5 behavior)."""
        a = Agent()

        with patch.object(a, "_select_mode", return_value="tool_loop"), \
                patch("pds_ultimate.core.agent.memory_manager") as mock_mem, \
                patch("pds_ultimate.core.agent.llm_engine") as mock_llm, \
                patch("pds_ultimate.core.agent.tool_registry"):

            mock_mem.get_context.return_value = ""
            mock_llm.chat_with_tools = AsyncMock(return_value={
                "type": "text",
                "content": "Balance is $100",
                "thought": "Checked balance",
            })

            response = await a.execute("show balance")

        assert response.answer == "Balance is $100"
        assert response.execution_mode == "tool_loop"

    @pytest.mark.asyncio
    async def test_execute_planned_mode(self):
        """Test planned mode (DAG + sub-agents)."""
        a = Agent()

        # Mock plan creation
        mock_plan = ExecutionPlan(goal="Test")
        step1 = PlanNode(id="step_1", description="Research")
        synth = PlanNode(id="synthesize", description="Combine",
                         depends_on=["step_1"])
        mock_plan.add_node(step1)
        mock_plan.add_node(synth)

        with patch.object(a, "_select_mode", return_value="planned"), \
                patch("pds_ultimate.core.agent.memory_manager") as mock_mem, \
                patch.object(a._planner, "create_plan", new_callable=AsyncMock, return_value=mock_plan), \
                patch("pds_ultimate.core.agent.llm_engine") as mock_agent_llm, \
                patch("pds_ultimate.core.llm_engine.llm_engine") as mock_sub_llm:

            mock_mem.get_context.return_value = ""
            mock_sub_llm.chat = AsyncMock(return_value="Research result")
            mock_agent_llm.chat = AsyncMock(
                return_value="Final synthesis answer")

            response = await a.execute(
                "Проанализируй и сравни данные по нескольким параметрам"
            )

        assert response.plan_used
        assert response.execution_mode == "planned"
        assert len(response.answer) > 0

    def test_global_agent(self):
        assert agent is not None
        assert isinstance(agent, Agent)

    def test_get_agent(self):
        assert get_agent() is agent

    def test_agent_response_new_fields(self):
        """Test that AgentResponse has the new v6 fields."""
        r = AgentResponse(answer="test")
        assert r.execution_mode == ""
        assert r.plan_stats == {}
        assert r.cache_stats == {}

    @pytest.mark.asyncio
    async def test_execute_error_handling(self):
        """Test graceful handling of LLM errors in simple mode."""
        a = Agent()

        with patch.object(a, "_select_mode", return_value="simple"), \
                patch("pds_ultimate.core.agent.memory_manager") as mock_mem, \
                patch("pds_ultimate.core.agent.llm_engine") as mock_llm:

            mock_mem.get_context.return_value = ""
            mock_llm.chat = AsyncMock(side_effect=Exception("API down"))

            response = await a.execute("hello")

        assert "Ошибка" in response.answer

    @pytest.mark.asyncio
    async def test_build_context(self):
        """Test context building with KV-cache."""
        a = Agent()

        with patch("pds_ultimate.core.agent.memory_manager") as mock_mem:
            mock_mem.get_context.return_value = "Some memory context"

            system_prompt, memory_ctx = a._build_context(
                "test query", chat_id=1)

        assert "PDS" in system_prompt  # System prompt should be there
        # Context optimizer should have processed the memory


class TestBackwardCompatibility:
    """Ensure v6 doesn't break existing imports and usage."""

    def test_imports(self):
        from pds_ultimate.core.agent import (
            Agent,
            AgentAction,
            AgentResponse,
            AgentStep,
            TaskVerifier,
            _sanitize_answer,
            agent,
            get_agent,
        )
        assert all([
            Agent, AgentAction, AgentResponse, AgentStep,
            TaskVerifier, _sanitize_answer, agent, get_agent,
        ])

    def test_agent_response_fields(self):
        """All v5 fields still exist."""
        r = AgentResponse(answer="test")
        assert hasattr(r, "answer")
        assert hasattr(r, "steps")
        assert hasattr(r, "tools_used")
        assert hasattr(r, "total_iterations")
        assert hasattr(r, "total_time_ms")
        assert hasattr(r, "memory_entries_created")
        assert hasattr(r, "plan_used")
        assert hasattr(r, "files_to_send")
        assert hasattr(r, "task_verified")
        assert hasattr(r, "quality_score")

    def test_agent_action_fields(self):
        a = AgentAction(action_type="test")
        assert hasattr(a, "tool_name")
        assert hasattr(a, "tool_params")
        assert hasattr(a, "thought")
        assert hasattr(a, "answer")
        assert hasattr(a, "confidence")
        assert hasattr(a, "parallel_calls")

    def test_execute_signature(self):
        """Agent.execute() has same signature as v5."""
        import inspect
        sig = inspect.signature(Agent.execute)
        params = list(sig.parameters.keys())
        assert "message" in params
        assert "chat_id" in params
        assert "history" in params
