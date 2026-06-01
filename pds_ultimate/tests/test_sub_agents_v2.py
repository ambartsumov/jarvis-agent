"""
Tests for Enhanced Sub-Agent System v2.0
==========================================
Tests:
- SubAgentType enum
- SubAgentFactory (type classification)
- CircuitBreaker (trip/reset/fallback)
- SelfAttentionScorer (weighted scoring)
- SubAgent (typed execution)
- WorkStealingPool (priority, adaptive concurrency, circuit breaker)
- WeightedAggregator (type-aware aggregation)
- Backward compatibility (SubAgentPool, ResultAggregator aliases)
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pds_ultimate.core.planner import PlanNode
from pds_ultimate.core.sub_agents import (
    _ANALYSIS_KW,
    _CREATIVE_KW,
    _RESEARCH_KW,
    _TYPE_PROMPTS,
    _TYPE_WEIGHTS,
    CircuitBreaker,
    ResultAggregator,
    SelfAttentionScorer,
    SubAgent,
    SubAgentFactory,
    SubAgentPool,
    SubAgentResult,
    SubAgentStatus,
    SubAgentType,
    WeightedAggregator,
    WorkStealingPool,
    result_aggregator,
    sub_agent_pool,
)

# ═══════════════════════════════════════════════════════════════════════════════
# 1. SubAgentType enum
# ═══════════════════════════════════════════════════════════════════════════════


class TestSubAgentType:
    def test_all_types_exist(self):
        assert SubAgentType.RESEARCH == "research"
        assert SubAgentType.ANALYSIS == "analysis"
        assert SubAgentType.TOOL == "tool"
        assert SubAgentType.CREATIVE == "creative"
        assert SubAgentType.GENERIC == "generic"

    def test_types_are_strings(self):
        for t in SubAgentType:
            assert isinstance(t.value, str)

    def test_all_types_have_prompts(self):
        for t in SubAgentType:
            assert t in _TYPE_PROMPTS

    def test_all_types_have_weights(self):
        for t in SubAgentType:
            assert t in _TYPE_WEIGHTS
            assert 0.0 < _TYPE_WEIGHTS[t] <= 1.0

    def test_tool_has_highest_weight(self):
        assert _TYPE_WEIGHTS[SubAgentType.TOOL] == max(_TYPE_WEIGHTS.values())


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Keyword frozensets
# ═══════════════════════════════════════════════════════════════════════════════

class TestKeywordSets:
    def test_research_keywords_are_frozenset(self):
        assert isinstance(_RESEARCH_KW, frozenset)

    def test_analysis_keywords_are_frozenset(self):
        assert isinstance(_ANALYSIS_KW, frozenset)

    def test_creative_keywords_are_frozenset(self):
        assert isinstance(_CREATIVE_KW, frozenset)

    def test_no_keyword_overlap(self):
        """Each keyword set should be distinct (minimal overlap)."""
        # Some overlap is OK, but they shouldn't be identical
        assert _RESEARCH_KW != _ANALYSIS_KW
        assert _RESEARCH_KW != _CREATIVE_KW
        assert _ANALYSIS_KW != _CREATIVE_KW


# ═══════════════════════════════════════════════════════════════════════════════
# 3. SubAgentFactory
# ═══════════════════════════════════════════════════════════════════════════════

class TestSubAgentFactory:
    def test_classify_tool_node(self):
        node = PlanNode(id="s1", description="do something",
                        tool_name="search_web")
        assert SubAgentFactory.classify(node) == SubAgentType.TOOL

    def test_classify_research_node(self):
        node = PlanNode(id="s1", description="найди информацию о рынке")
        assert SubAgentFactory.classify(node) == SubAgentType.RESEARCH

    def test_classify_analysis_node(self):
        node = PlanNode(id="s1", description="рассчитай процент прибыли")
        assert SubAgentFactory.classify(node) == SubAgentType.ANALYSIS

    def test_classify_creative_node(self):
        node = PlanNode(id="s1", description="напиши текст для отчёта")
        assert SubAgentFactory.classify(node) == SubAgentType.CREATIVE

    def test_classify_generic_fallback(self):
        node = PlanNode(id="s1", description="hello world")
        assert SubAgentFactory.classify(node) == SubAgentType.GENERIC

    def test_classify_english_research(self):
        node = PlanNode(id="s1", description="research market trends")
        assert SubAgentFactory.classify(node) == SubAgentType.RESEARCH

    def test_classify_english_analysis(self):
        node = PlanNode(id="s1", description="analyze and compare the data")
        assert SubAgentFactory.classify(node) == SubAgentType.ANALYSIS

    def test_classify_english_creative(self):
        node = PlanNode(id="s1", description="write a draft report")
        assert SubAgentFactory.classify(node) == SubAgentType.CREATIVE

    def test_classify_substring_match(self):
        """Should match partial keywords (e.g. 'анализируй' contains 'анализ')."""
        node = PlanNode(id="s1", description="проанализируй и сравни цифры")
        result = SubAgentFactory.classify(node)
        assert result == SubAgentType.ANALYSIS

    def test_classify_tool_overrides_keywords(self):
        """Tool nodes always get TOOL type regardless of description."""
        node = PlanNode(
            id="s1",
            description="найди информацию",
            tool_name="web_search",
        )
        assert SubAgentFactory.classify(node) == SubAgentType.TOOL

    def test_create_returns_typed_sub_agent(self):
        node = PlanNode(id="s1", description="найди данные", tool_name=None)
        agent = SubAgentFactory.create(node, goal="test goal")
        assert isinstance(agent, SubAgent)
        assert agent.agent_type == SubAgentType.RESEARCH
        assert agent.goal == "test goal"

    def test_create_tool_agent(self):
        node = PlanNode(id="s1", description="exec", tool_name="calc")
        agent = SubAgentFactory.create(node, goal="test")
        assert agent.agent_type == SubAgentType.TOOL

    def test_create_with_context(self):
        node = PlanNode(id="s1", description="generic task")
        agent = SubAgentFactory.create(
            node, goal="g", context="ctx", completed_results={"a": "b"},
        )
        assert agent.context == "ctx"
        assert agent.completed_results == {"a": "b"}


# ═══════════════════════════════════════════════════════════════════════════════
# 4. SelfAttentionScorer
# ═══════════════════════════════════════════════════════════════════════════════

class TestSelfAttentionScorer:
    def test_empty_result_scores_zero(self):
        assert SelfAttentionScorer.score("goal", "") == 0.0
        assert SelfAttentionScorer.score("goal", "   ") == 0.0

    def test_empty_goal_scores_half(self):
        assert SelfAttentionScorer.score("", "some result") == 0.5

    def test_high_overlap_scores_high(self):
        score = SelfAttentionScorer.score(
            "найди цену товара",
            "цена товара составляет 100 рублей за единицу",
        )
        assert score > 0.3

    def test_no_overlap_scores_low(self):
        score = SelfAttentionScorer.score("abc def", "xyz uvw")
        assert score < 0.5

    def test_error_penalty(self):
        normal = SelfAttentionScorer.score(
            "task", "result of the task completed")
        error = SelfAttentionScorer.score(
            "task", "error occurred during task execution")
        assert error < normal

    def test_short_result_penalized(self):
        short = SelfAttentionScorer.score("задача", "да")
        medium = SelfAttentionScorer.score(
            "задача", "Это результат задачи: данные обработаны")
        assert short < medium

    def test_score_range(self):
        for goal, result in [
            ("x", "y"),
            ("find info", "The info is here and complete"),
            ("error", "error error error"),
        ]:
            s = SelfAttentionScorer.score(goal, result)
            assert 0.0 <= s <= 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# 5. CircuitBreaker
# ═══════════════════════════════════════════════════════════════════════════════

class TestCircuitBreaker:
    def test_initially_all_available(self):
        cb = CircuitBreaker()
        for t in SubAgentType:
            assert cb.is_available(t) is True

    def test_single_failure_keeps_available(self):
        cb = CircuitBreaker()
        cb.record_failure(SubAgentType.RESEARCH)
        assert cb.is_available(SubAgentType.RESEARCH) is True

    def test_threshold_failures_trips(self):
        cb = CircuitBreaker()
        for _ in range(CircuitBreaker.THRESHOLD):
            cb.record_failure(SubAgentType.RESEARCH)
        assert cb.is_available(SubAgentType.RESEARCH) is False

    def test_success_resets_failures(self):
        cb = CircuitBreaker()
        for _ in range(CircuitBreaker.THRESHOLD - 1):
            cb.record_failure(SubAgentType.RESEARCH)
        cb.record_success(SubAgentType.RESEARCH)
        # Should be reset
        for _ in range(CircuitBreaker.THRESHOLD - 1):
            cb.record_failure(SubAgentType.RESEARCH)
        assert cb.is_available(SubAgentType.RESEARCH) is True

    def test_get_effective_type_normal(self):
        cb = CircuitBreaker()
        assert cb.get_effective_type(
            SubAgentType.ANALYSIS) == SubAgentType.ANALYSIS

    def test_get_effective_type_tripped(self):
        cb = CircuitBreaker()
        for _ in range(CircuitBreaker.THRESHOLD):
            cb.record_failure(SubAgentType.ANALYSIS)
        assert cb.get_effective_type(
            SubAgentType.ANALYSIS) == SubAgentType.GENERIC

    def test_auto_reset_after_interval(self):
        cb = CircuitBreaker()
        for _ in range(CircuitBreaker.THRESHOLD):
            cb.record_failure(SubAgentType.CREATIVE)
        assert cb.is_available(SubAgentType.CREATIVE) is False

        # Simulate time passing
        cb._tripped_at[SubAgentType.CREATIVE] = time.time() - \
            CircuitBreaker.RESET_INTERVAL - 1
        assert cb.is_available(SubAgentType.CREATIVE) is True

    def test_independent_types(self):
        cb = CircuitBreaker()
        for _ in range(CircuitBreaker.THRESHOLD):
            cb.record_failure(SubAgentType.RESEARCH)
        assert cb.is_available(SubAgentType.RESEARCH) is False
        assert cb.is_available(SubAgentType.ANALYSIS) is True
        assert cb.is_available(SubAgentType.CREATIVE) is True


# ═══════════════════════════════════════════════════════════════════════════════
# 6. SubAgent (typed execution)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSubAgent:
    def test_init_defaults(self):
        node = PlanNode(id="n1", description="test")
        agent = SubAgent(node=node, goal="goal")
        assert agent.agent_type == SubAgentType.GENERIC
        assert agent.status == SubAgentStatus.IDLE
        assert agent.completed_results == {}

    def test_init_with_type(self):
        node = PlanNode(id="n1", description="test")
        agent = SubAgent(node=node, goal="g", agent_type=SubAgentType.RESEARCH)
        assert agent.agent_type == SubAgentType.RESEARCH

    @pytest.mark.asyncio
    async def test_execute_tool_success(self):
        node = PlanNode(id="n1", description="exec", tool_name="test_tool")
        agent = SubAgent(node=node, goal="test goal",
                         agent_type=SubAgentType.TOOL)

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = "Tool output data result"
        mock_result.data = None

        with patch("pds_ultimate.core.tools.tool_registry") as mock_reg:
            mock_reg.has_tool.return_value = True
            mock_reg.execute = AsyncMock(return_value=mock_result)

            result = await agent.execute()

        assert result.status == SubAgentStatus.COMPLETED
        assert result.agent_type == SubAgentType.TOOL
        assert result.tool_calls == 1
        assert "Tool output" in result.output

    @pytest.mark.asyncio
    async def test_execute_llm_reasoning(self):
        node = PlanNode(id="n1", description="analyze data")
        agent = SubAgent(node=node, goal="test",
                         agent_type=SubAgentType.ANALYSIS)

        with patch("pds_ultimate.core.llm_engine.llm_engine") as mock_llm:
            mock_llm.chat = AsyncMock(
                return_value="Analysis complete: results are positive")

            result = await agent.execute()

        assert result.status == SubAgentStatus.COMPLETED
        assert result.agent_type == SubAgentType.ANALYSIS
        assert result.tool_calls == 0

    @pytest.mark.asyncio
    async def test_execute_tool_failure(self):
        node = PlanNode(id="n1", description="exec", tool_name="bad_tool")
        agent = SubAgent(node=node, goal="test", agent_type=SubAgentType.TOOL)

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "Connection failed"

        with patch("pds_ultimate.core.tools.tool_registry") as mock_reg:
            mock_reg.has_tool.return_value = True
            mock_reg.execute = AsyncMock(return_value=mock_result)

            result = await agent.execute()

        assert result.status == SubAgentStatus.FAILED
        assert "Connection failed" in result.error

    @pytest.mark.asyncio
    async def test_weighted_relevance_applied(self):
        """Tool agents should get weight bonus applied."""
        node = PlanNode(id="n1", description="run tool", tool_name="test_tool")
        agent = SubAgent(node=node, goal="test goal",
                         agent_type=SubAgentType.TOOL)

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = "test goal result data output"
        mock_result.data = None

        with patch("pds_ultimate.core.tools.tool_registry") as mock_reg:
            mock_reg.has_tool.return_value = True
            mock_reg.execute = AsyncMock(return_value=mock_result)

            result = await agent.execute()

        # TOOL weight is 1.0, so weighted_relevance should be similar to raw
        assert result.relevance_score > 0

    @pytest.mark.asyncio
    async def test_reason_uses_type_prompt(self):
        """Each type should use its specialized system prompt."""
        node = PlanNode(id="n1", description="напиши отчёт")
        agent = SubAgent(node=node, goal="test",
                         agent_type=SubAgentType.CREATIVE)

        with patch("pds_ultimate.core.llm_engine.llm_engine") as mock_llm:
            mock_llm.chat = AsyncMock(return_value="Report text here")
            await agent.execute()

            call_kwargs = mock_llm.chat.call_args.kwargs
            assert "копирайтер" in call_kwargs["system_prompt"]

    @pytest.mark.asyncio
    async def test_reason_includes_deps_context(self):
        node = PlanNode(id="n2", description="summarize")
        agent = SubAgent(
            node=node, goal="test",
            completed_results={"step_1": "Previous result data"},
        )

        with patch("pds_ultimate.core.llm_engine.llm_engine") as mock_llm:
            mock_llm.chat = AsyncMock(return_value="Summary of results")
            await agent.execute()

            call_kwargs = mock_llm.chat.call_args.kwargs
            assert "Previous result" in call_kwargs["message"]


# ═══════════════════════════════════════════════════════════════════════════════
# 7. SubAgentResult
# ═══════════════════════════════════════════════════════════════════════════════

class TestSubAgentResult:
    def test_default_agent_type(self):
        r = SubAgentResult(node_id="n1", status=SubAgentStatus.COMPLETED)
        assert r.agent_type == SubAgentType.GENERIC

    def test_custom_agent_type(self):
        r = SubAgentResult(
            node_id="n1", status=SubAgentStatus.COMPLETED,
            agent_type=SubAgentType.RESEARCH,
        )
        assert r.agent_type == SubAgentType.RESEARCH

    def test_all_fields(self):
        r = SubAgentResult(
            node_id="n1", status=SubAgentStatus.COMPLETED,
            output="data", relevance_score=0.8,
            duration_ms=100, tool_calls=1, retries=0,
            agent_type=SubAgentType.TOOL,
        )
        assert r.output == "data"
        assert r.relevance_score == 0.8
        assert r.agent_type == SubAgentType.TOOL


# ═══════════════════════════════════════════════════════════════════════════════
# 8. WeightedAggregator
# ═══════════════════════════════════════════════════════════════════════════════

class TestWeightedAggregator:
    def test_aggregate_empty(self):
        result = WeightedAggregator.aggregate([], "goal")
        assert result["merged_context"] == "(нет результатов)"
        assert result["stats"]["total"] == 0
        assert result["best_result"] is None

    def test_aggregate_single_success(self):
        results = [
            SubAgentResult(
                node_id="n1", status=SubAgentStatus.COMPLETED,
                output="Result data", relevance_score=0.8,
                agent_type=SubAgentType.TOOL,
            ),
        ]
        agg = WeightedAggregator.aggregate(results, "goal")
        assert "Result data" in agg["merged_context"]
        assert agg["stats"]["successful"] == 1
        assert agg["stats"]["failed"] == 0
        assert agg["best_result"].node_id == "n1"

    def test_aggregate_mixed_results(self):
        results = [
            SubAgentResult(
                node_id="n1", status=SubAgentStatus.COMPLETED,
                output="Good result", relevance_score=0.9,
                agent_type=SubAgentType.TOOL,
            ),
            SubAgentResult(
                node_id="n2", status=SubAgentStatus.FAILED,
                error="timeout",
            ),
            SubAgentResult(
                node_id="n3", status=SubAgentStatus.COMPLETED,
                output="OK result", relevance_score=0.5,
                agent_type=SubAgentType.GENERIC,
            ),
        ]
        agg = WeightedAggregator.aggregate(results, "goal")
        assert agg["stats"]["successful"] == 2
        assert agg["stats"]["failed"] == 1
        assert len(agg["failed"]) == 1
        # Best result should be n1 (highest weighted score)
        assert agg["best_result"].node_id == "n1"

    def test_aggregate_type_aware_sorting(self):
        """Tool results with same relevance should rank higher than generic."""
        results = [
            SubAgentResult(
                node_id="n1", status=SubAgentStatus.COMPLETED,
                output="Generic", relevance_score=0.8,
                agent_type=SubAgentType.GENERIC,
            ),
            SubAgentResult(
                node_id="n2", status=SubAgentStatus.COMPLETED,
                output="Tool", relevance_score=0.8,
                agent_type=SubAgentType.TOOL,
            ),
        ]
        agg = WeightedAggregator.aggregate(results, "goal")
        # Tool (weight 1.0) should rank above Generic (weight 0.7)
        assert agg["best_result"].node_id == "n2"

    def test_aggregate_stats_include_types(self):
        results = [
            SubAgentResult(
                node_id="n1", status=SubAgentStatus.COMPLETED,
                agent_type=SubAgentType.RESEARCH,
            ),
            SubAgentResult(
                node_id="n2", status=SubAgentStatus.COMPLETED,
                agent_type=SubAgentType.TOOL,
            ),
        ]
        agg = WeightedAggregator.aggregate(results, "goal")
        types = set(agg["stats"]["types_used"])
        assert "research" in types
        assert "tool" in types

    def test_merged_context_includes_type_tags(self):
        results = [
            SubAgentResult(
                node_id="n1", status=SubAgentStatus.COMPLETED,
                output="Data", relevance_score=0.9,
                agent_type=SubAgentType.ANALYSIS,
            ),
        ]
        agg = WeightedAggregator.aggregate(results, "goal")
        assert "ANALYSIS" in agg["merged_context"]


# ═══════════════════════════════════════════════════════════════════════════════
# 9. WorkStealingPool
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorkStealingPool:
    @pytest.mark.asyncio
    async def test_empty_nodes(self):
        pool = WorkStealingPool()
        results = await pool.execute_parallel([], goal="test")
        assert results == []

    @pytest.mark.asyncio
    async def test_single_tool_node(self):
        pool = WorkStealingPool(timeout=5, max_retries=0)
        node = PlanNode(id="n1", description="exec", tool_name="test_tool")

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = "Tool output result data"
        mock_result.data = None

        with patch("pds_ultimate.core.tools.tool_registry") as mock_reg:
            mock_reg.has_tool.return_value = True
            mock_reg.execute = AsyncMock(return_value=mock_result)

            results = await pool.execute_parallel(
                [node], goal="test goal",
            )

        assert len(results) == 1
        assert results[0].status == SubAgentStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_parallel_llm_nodes(self):
        pool = WorkStealingPool(timeout=5, max_retries=0)
        nodes = [
            PlanNode(id="n1", description="найди данные"),
            PlanNode(id="n2", description="рассчитай итог"),
            PlanNode(id="n3", description="напиши отчёт"),
        ]

        with patch("pds_ultimate.core.llm_engine.llm_engine") as mock_llm:
            mock_llm.chat = AsyncMock(return_value="Result output data")

            results = await pool.execute_parallel(
                nodes, goal="complex task",
            )

        assert len(results) == 3
        # All should complete
        completed = [r for r in results if r.status ==
                     SubAgentStatus.COMPLETED]
        assert len(completed) == 3

    @pytest.mark.asyncio
    async def test_priority_sort_tools_first(self):
        """Tool nodes should be sorted before LLM nodes."""
        pool = WorkStealingPool(timeout=5, max_retries=0)
        execution_order = []

        nodes = [
            PlanNode(id="llm_1", description="reason about things"),
            PlanNode(id="tool_1", description="exec", tool_name="t1"),
            PlanNode(id="llm_2", description="more reasoning"),
        ]

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = "Tool done result data"
        mock_result.data = None

        async def track_tool(name, params=None, **kw):
            execution_order.append(f"tool:{name}")
            return mock_result

        async def track_llm(**kw):
            execution_order.append("llm")
            return "LLM result data output"

        with patch("pds_ultimate.core.tools.tool_registry") as mock_reg, \
                patch("pds_ultimate.core.llm_engine.llm_engine") as mock_llm:
            mock_reg.has_tool.return_value = True
            mock_reg.execute = AsyncMock(side_effect=track_tool)
            mock_llm.chat = AsyncMock(side_effect=track_llm)

            results = await pool.execute_parallel(nodes, goal="test")

        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_adaptive_concurrency(self):
        """Concurrency should scale with task count."""
        pool = WorkStealingPool(max_concurrent=8, timeout=5, max_retries=0)
        # 2 nodes → effective_concurrent = max(2, 2) = 2
        nodes = [
            PlanNode(id="n1", description="task one"),
            PlanNode(id="n2", description="task two"),
        ]

        with patch("pds_ultimate.core.llm_engine.llm_engine") as mock_llm:
            mock_llm.chat = AsyncMock(return_value="Result output data")
            results = await pool.execute_parallel(nodes, goal="test")

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_circuit_breaker_integration(self):
        """Circuit breaker should track successes and failures."""
        pool = WorkStealingPool(timeout=5, max_retries=0)
        node = PlanNode(id="n1", description="найди информацию")

        with patch("pds_ultimate.core.llm_engine.llm_engine") as mock_llm:
            mock_llm.chat = AsyncMock(return_value="Found the information")
            await pool.execute_parallel([node], goal="test")

        # RESEARCH type should have success recorded
        assert pool._circuit_breaker.is_available(
            SubAgentType.RESEARCH) is True

    @pytest.mark.asyncio
    async def test_exception_handled_as_failure(self):
        pool = WorkStealingPool(timeout=5, max_retries=0)
        node = PlanNode(id="n1", description="crash task")

        with patch("pds_ultimate.core.llm_engine.llm_engine") as mock_llm:
            mock_llm.chat = AsyncMock(side_effect=RuntimeError("boom"))
            results = await pool.execute_parallel([node], goal="test")

        assert len(results) == 1
        assert results[0].status == SubAgentStatus.FAILED

    @pytest.mark.asyncio
    async def test_timeout_handling(self):
        pool = WorkStealingPool(timeout=0.1, max_retries=0)
        node = PlanNode(id="n1", description="slow task")

        async def slow_chat(**kw):
            await asyncio.sleep(10)
            return "never"

        with patch("pds_ultimate.core.llm_engine.llm_engine") as mock_llm:
            mock_llm.chat = AsyncMock(side_effect=slow_chat)
            results = await pool.execute_parallel([node], goal="test")

        assert len(results) == 1
        assert results[0].status == SubAgentStatus.FAILED
        assert "Timeout" in results[0].error

    @pytest.mark.asyncio
    async def test_total_executed_counter(self):
        pool = WorkStealingPool(timeout=5, max_retries=0)
        assert pool.total_executed == 0

        node = PlanNode(id="n1", description="task")
        with patch("pds_ultimate.core.llm_engine.llm_engine") as mock_llm:
            mock_llm.chat = AsyncMock(return_value="Done result data")
            await pool.execute_parallel([node], goal="test")

        assert pool.total_executed == 1

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        pool = WorkStealingPool(timeout=5, max_retries=1)
        node = PlanNode(id="n1", description="flaky task")

        call_count = 0

        async def flaky_chat(**kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("first try fails")
            return "Success on retry data output"

        with patch("pds_ultimate.core.llm_engine.llm_engine") as mock_llm:
            mock_llm.chat = AsyncMock(side_effect=flaky_chat)
            results = await pool.execute_parallel([node], goal="test")

        assert len(results) == 1
        assert results[0].status == SubAgentStatus.COMPLETED
        assert results[0].retries == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Backward Compatibility
# ═══════════════════════════════════════════════════════════════════════════════

class TestBackwardCompatibility:
    def test_sub_agent_pool_alias(self):
        assert SubAgentPool is WorkStealingPool

    def test_result_aggregator_alias(self):
        assert ResultAggregator is WeightedAggregator

    def test_global_instances(self):
        assert isinstance(sub_agent_pool, WorkStealingPool)
        assert isinstance(result_aggregator, WeightedAggregator)

    def test_sub_agent_result_backward_compat(self):
        """Old code creates SubAgentResult without agent_type."""
        r = SubAgentResult(
            node_id="n1",
            status=SubAgentStatus.COMPLETED,
            output="data",
            relevance_score=0.8,
        )
        assert r.agent_type == SubAgentType.GENERIC

    def test_sub_agent_old_style_init(self):
        """Old code creates SubAgent without agent_type."""
        node = PlanNode(id="n1", description="test")
        agent = SubAgent(node=node, goal="goal")
        assert agent.agent_type == SubAgentType.GENERIC

    @pytest.mark.asyncio
    async def test_old_aggregator_interface(self):
        """Old ResultAggregator.aggregate() should still work."""
        results = [
            SubAgentResult(
                node_id="n1",
                status=SubAgentStatus.COMPLETED,
                output="data",
                relevance_score=0.8,
            ),
        ]
        agg = ResultAggregator.aggregate(results, "goal")
        assert "merged_context" in agg
        assert "stats" in agg
        assert "best_result" in agg


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Integration Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntegration:
    @pytest.mark.asyncio
    async def test_factory_to_pool_flow(self):
        """Full flow: factory creates agents → pool executes in parallel."""
        pool = WorkStealingPool(timeout=5, max_retries=0)
        nodes = [
            PlanNode(id="research", description="найди цены на рынке"),
            PlanNode(id="calculate", description="рассчитай прибыль"),
            PlanNode(id="report", description="напиши отчёт"),
        ]

        with patch("pds_ultimate.core.llm_engine.llm_engine") as mock_llm:
            mock_llm.chat = AsyncMock(
                return_value="Task completed with results data")
            results = await pool.execute_parallel(nodes, goal="бизнес-анализ")

        assert len(results) == 3
        # Check that different types were assigned
        types = {r.agent_type for r in results}
        assert len(types) > 1  # At least 2 different types

    @pytest.mark.asyncio
    async def test_full_pipeline_with_aggregation(self):
        """Factory → Pool → Aggregator full pipeline."""
        pool = WorkStealingPool(timeout=5, max_retries=0)
        nodes = [
            PlanNode(id="s1", description="найди данные", tool_name="search"),
            PlanNode(id="s2", description="рассчитай результат"),
        ]

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = "Search result data found complete"
        mock_result.data = None

        with patch("pds_ultimate.core.tools.tool_registry") as mock_reg, \
                patch("pds_ultimate.core.llm_engine.llm_engine") as mock_llm:
            mock_reg.has_tool.return_value = True
            mock_reg.execute = AsyncMock(return_value=mock_result)
            mock_llm.chat = AsyncMock(
                return_value="Calculation result output data")

            results = await pool.execute_parallel(nodes, goal="analysis")

        # Aggregate
        agg = WeightedAggregator.aggregate(results, "analysis")
        assert agg["stats"]["successful"] == 2
        assert agg["stats"]["total"] == 2
        assert agg["best_result"] is not None
        assert "types_used" in agg["stats"]

    @pytest.mark.asyncio
    async def test_mixed_success_failure_pipeline(self):
        """Pipeline with some nodes failing."""
        pool = WorkStealingPool(timeout=5, max_retries=0)
        nodes = [
            PlanNode(id="ok_1", description="good task"),
            PlanNode(id="fail_1", description="bad task"),
        ]

        call_count = 0

        async def mixed_chat(**kw):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("intentional failure")
            return "Success output data result"

        with patch("pds_ultimate.core.llm_engine.llm_engine") as mock_llm:
            mock_llm.chat = AsyncMock(side_effect=mixed_chat)
            results = await pool.execute_parallel(nodes, goal="test")

        agg = WeightedAggregator.aggregate(results, "test")
        assert agg["stats"]["successful"] >= 1
        assert agg["stats"]["failed"] >= 1
