"""
PDS-Ultimate Enhanced Sub-Agent System v2.0
=============================================
Typed, parallel sub-agents with work-stealing pool.

ARCHITECTURE:
    Orchestrator (Agent v6.1)
        ├── ResearchAgent   (search + web tools)
        ├── AnalysisAgent   (reasoning + calculations)
        ├── ToolAgent       (direct tool execution — fastest)
        ├── CreativeAgent   (text generation, formatting)
        └── GenericAgent    (fallback for anything else)
             ↓
        WorkStealingPool  (priority queue + adaptive concurrency)
             ↓
        WeightedAggregator (type-aware scoring)

KEY IMPROVEMENTS OVER v1.0:
- Typed sub-agents with specialized system prompts
- SubAgentFactory: auto-creates the right type from task description
- WorkStealingPool: priority queue, circuit breaker, adaptive workers
- WeightedAggregator: tool results scored higher than pure reasoning
- __slots__ on hot classes for less memory
- Frozen constants for O(1) keyword lookups
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pds_ultimate.config import logger
from pds_ultimate.core.planner import NodeStatus, PlanNode

# ─── Constants ───────────────────────────────────────────────────────────────

MAX_CONCURRENT_AGENTS = 4
SUB_AGENT_TIMEOUT = 60  # seconds per sub-agent
MAX_RETRIES = 2

# ─── Sub-Agent Types ────────────────────────────────────────────────────────


class SubAgentType(str, Enum):
    """Typed sub-agent specializations."""
    RESEARCH = "research"
    ANALYSIS = "analysis"
    TOOL = "tool"
    CREATIVE = "creative"
    GENERIC = "generic"


# Keywords for auto-detection (frozensets for O(1) lookup)
_RESEARCH_KW: frozenset[str] = frozenset({
    "найди", "поиск", "search", "google", "найти", "искать",
    "узнай", "проверь", "информаци", "данные", "источник",
    "research", "investigate", "browse", "web", "интернет",
})

_ANALYSIS_KW: frozenset[str] = frozenset({
    "анализ", "сравн", "рассчит", "вычисл", "статистик",
    "analyze", "compare", "calculate", "compute", "evaluate",
    "оцен", "процент", "формул", "итог", "сумм",
})

_CREATIVE_KW: frozenset[str] = frozenset({
    "напиши", "создай", "сочин", "придумай", "сформулируй",
    "write", "create", "compose", "draft", "format",
    "текст", "письмо", "отчёт", "отчет", "шаблон",
})

# Type-specific system prompts
_TYPE_PROMPTS: dict[SubAgentType, str] = {
    SubAgentType.RESEARCH: (
        "Ты — суб-агент-исследователь. Найди точную информацию. "
        "Используй инструменты поиска если доступны. Кратко, с фактами."
    ),
    SubAgentType.ANALYSIS: (
        "Ты — суб-агент-аналитик. Анализируй данные, считай, сравнивай. "
        "Будь точен в цифрах. Покажи ход рассуждений кратко."
    ),
    SubAgentType.TOOL: (
        "Ты — суб-агент для выполнения инструмента. "
        "Выполни команду и верни результат без лишних комментариев."
    ),
    SubAgentType.CREATIVE: (
        "Ты — суб-агент-копирайтер. Пиши ясно, структурированно, "
        "по делу. Не лей воду. Формат: списки, заголовки где уместно."
    ),
    SubAgentType.GENERIC: (
        "Ты — суб-агент, выполняющий ОДНУ конкретную задачу. "
        "Ответь кратко и по делу. Не повторяй задание."
    ),
}

# Scoring weights by type (tool results are most reliable)
_TYPE_WEIGHTS: dict[SubAgentType, float] = {
    SubAgentType.TOOL: 1.0,
    SubAgentType.RESEARCH: 0.85,
    SubAgentType.ANALYSIS: 0.9,
    SubAgentType.CREATIVE: 0.75,
    SubAgentType.GENERIC: 0.7,
}


# ─── Self-Attention Scoring ─────────────────────────────────────────────────

class SelfAttentionScorer:
    """
    Lightweight self-attention scoring for result relevance.

    Score range: 0.0 - 1.0.
    Uses Jaccard keyword overlap + length heuristic + error penalty.
    """

    __slots__ = ()

    @staticmethod
    def score(goal: str, result: str) -> float:
        if not result or not result.strip():
            return 0.0

        goal_words = set(goal.lower().split())
        result_words = set(result.lower().split())

        if not goal_words:
            return 0.5

        # Jaccard similarity
        intersection = goal_words & result_words
        union = goal_words | result_words
        jaccard = len(intersection) / len(union) if union else 0.0

        # Length factor
        rlen = len(result)
        if rlen < 10:
            len_factor = 0.3
        elif rlen < 50:
            len_factor = 0.7
        elif rlen < 2000:
            len_factor = 1.0
        else:
            len_factor = 0.8

        # Error penalty
        _ERR = {"error", "ошибка", "fail", "exception", "traceback"}
        error_penalty = 0.5 if (result_words & _ERR) else 1.0

        return min(1.0, max(0.0,
                            (jaccard * 0.6 + len_factor * 0.3 + 0.1) * error_penalty))


# ─── Sub-Agent Factory ──────────────────────────────────────────────────────

class SubAgentFactory:
    """
    Auto-creates typed sub-agents from task descriptions.

    Analyzes node description + tool_name to pick the best type.
    """

    __slots__ = ()

    @staticmethod
    def classify(node: PlanNode) -> SubAgentType:
        """Determine sub-agent type for a plan node."""
        # Direct tool execution → ToolAgent
        if node.tool_name:
            return SubAgentType.TOOL

        desc_lower = node.description.lower()
        words = set(desc_lower.split())

        # Check keyword overlap with each type
        scores: dict[SubAgentType, int] = {
            SubAgentType.RESEARCH: len(words & _RESEARCH_KW),
            SubAgentType.ANALYSIS: len(words & _ANALYSIS_KW),
            SubAgentType.CREATIVE: len(words & _CREATIVE_KW),
        }

        # Also check substring matches for partial keywords
        for word in desc_lower.split():
            for kw in _RESEARCH_KW:
                if kw in word and len(kw) >= 4:
                    scores[SubAgentType.RESEARCH] += 1
                    break
            for kw in _ANALYSIS_KW:
                if kw in word and len(kw) >= 4:
                    scores[SubAgentType.ANALYSIS] += 1
                    break
            for kw in _CREATIVE_KW:
                if kw in word and len(kw) >= 4:
                    scores[SubAgentType.CREATIVE] += 1
                    break

        best_type = max(scores, key=scores.get)  # type: ignore[arg-type]
        if scores[best_type] > 0:
            return best_type

        return SubAgentType.GENERIC

    @staticmethod
    def create(
        node: PlanNode,
        goal: str,
        context: str = "",
        completed_results: dict[str, str] | None = None,
    ) -> SubAgent:
        """Create a typed SubAgent for the given node."""
        agent_type = SubAgentFactory.classify(node)
        return SubAgent(
            node=node,
            goal=goal,
            context=context,
            completed_results=completed_results,
            agent_type=agent_type,
        )


# ─── Sub-Agent Result & Status ──────────────────────────────────────────────

class SubAgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class SubAgentResult:
    """Result from a single sub-agent execution."""
    node_id: str
    status: SubAgentStatus
    output: str = ""
    error: str | None = None
    relevance_score: float = 0.0
    duration_ms: int = 0
    tool_calls: int = 0
    retries: int = 0
    agent_type: SubAgentType = SubAgentType.GENERIC


# ─── Sub-Agent ───────────────────────────────────────────────────────────────

class SubAgent:
    """
    Typed, isolated execution unit for a single DAG node.

    Each sub-agent:
    - Has a specialized system prompt based on type
    - Can use tools or LLM reasoning
    - Has its own conversation context
    - Reports typed SubAgentResult
    """

    __slots__ = (
        "node", "goal", "context", "completed_results",
        "agent_type", "status", "_start_time",
    )

    def __init__(
        self,
        node: PlanNode,
        goal: str,
        context: str = "",
        completed_results: dict[str, str] | None = None,
        agent_type: SubAgentType = SubAgentType.GENERIC,
    ):
        self.node = node
        self.goal = goal
        self.context = context
        self.completed_results = completed_results or {}
        self.agent_type = agent_type
        self.status = SubAgentStatus.IDLE
        self._start_time: float = 0.0

    async def execute(self) -> SubAgentResult:
        """
        Execute this sub-agent's task.

        Strategy:
        1. TOOL type + node has tool → call tool directly (fastest path)
        2. Otherwise → LLM reasoning with type-specific prompt
        """
        from pds_ultimate.core.llm_engine import llm_engine
        from pds_ultimate.core.tools import tool_registry

        self.status = SubAgentStatus.RUNNING
        self._start_time = time.time()
        self.node.mark_running()

        tool_calls = 0

        try:
            if self.node.tool_name and tool_registry.has_tool(self.node.tool_name):
                # Fast path: direct tool execution
                tool_result = await tool_registry.execute(
                    self.node.tool_name,
                    self.node.tool_params,
                )
                tool_calls = 1
                if tool_result.success:
                    output = tool_result.output or str(tool_result.data)
                else:
                    raise RuntimeError(
                        f"Tool '{self.node.tool_name}' failed: {tool_result.error}"
                    )
            else:
                # LLM reasoning with type-specific prompt
                output = await self._reason(llm_engine)

            # Score relevance
            relevance = SelfAttentionScorer.score(self.goal, output)

            # Apply type weight bonus
            type_weight = _TYPE_WEIGHTS.get(self.agent_type, 0.7)
            weighted_relevance = min(1.0, relevance * type_weight + (1 - type_weight) * 0.5)

            self.node.mark_completed(output)
            self.status = SubAgentStatus.COMPLETED
            duration = int((time.time() - self._start_time) * 1000)

            logger.info(
                f"SubAgent [{self.node.id}|{self.agent_type.value}] completed: "
                f"{duration}ms, relevance={weighted_relevance:.2f}, tools={tool_calls}"
            )

            return SubAgentResult(
                node_id=self.node.id,
                status=SubAgentStatus.COMPLETED,
                output=output,
                relevance_score=weighted_relevance,
                duration_ms=duration,
                tool_calls=tool_calls,
                agent_type=self.agent_type,
            )

        except Exception as e:
            error_msg = str(e)[:500]
            self.node.mark_failed(error_msg)
            self.status = SubAgentStatus.FAILED
            duration = int((time.time() - self._start_time) * 1000)

            logger.error(f"SubAgent [{self.node.id}|{self.agent_type.value}] failed: {error_msg}")

            return SubAgentResult(
                node_id=self.node.id,
                status=SubAgentStatus.FAILED,
                error=error_msg,
                duration_ms=duration,
                tool_calls=tool_calls,
                agent_type=self.agent_type,
            )

    async def _reason(self, llm_engine: Any) -> str:
        """LLM reasoning with type-specific system prompt."""
        # Build context from completed dependencies
        deps_context = ""
        if self.completed_results:
            deps_parts = [
                f"  [{nid}]: {res[:300]}"
                for nid, res in self.completed_results.items()
            ]
            deps_context = "\n\nРезультаты предыдущих шагов:\n" + "\n".join(deps_parts)

        prompt = f"Задача: {self.node.description}\nОбщая цель: {self.goal}{deps_context}"
        if self.context:
            prompt += f"\n\nДополнительный контекст:\n{self.context}"

        system_prompt = _TYPE_PROMPTS.get(self.agent_type, _TYPE_PROMPTS[SubAgentType.GENERIC])

        return await llm_engine.chat(
            message=prompt,
            system_prompt=system_prompt,
            task_type="sub_agent_task",
            temperature=0.3,
        )


# ─── Circuit Breaker ────────────────────────────────────────────────────────

class CircuitBreaker:
    """
    Per-type circuit breaker.

    After THRESHOLD consecutive failures for a sub-agent type,
    that type is temporarily disabled (falls back to GENERIC).
    Auto-resets after RESET_INTERVAL seconds.
    """

    THRESHOLD = 3
    RESET_INTERVAL = 300.0  # 5 minutes

    __slots__ = ("_failures", "_tripped_at")

    def __init__(self) -> None:
        self._failures: dict[SubAgentType, int] = {}
        self._tripped_at: dict[SubAgentType, float] = {}

    def record_success(self, agent_type: SubAgentType) -> None:
        self._failures.pop(agent_type, None)
        self._tripped_at.pop(agent_type, None)

    def record_failure(self, agent_type: SubAgentType) -> None:
        self._failures[agent_type] = self._failures.get(agent_type, 0) + 1
        if self._failures[agent_type] >= self.THRESHOLD:
            self._tripped_at[agent_type] = time.time()
            logger.warning(f"Circuit breaker TRIPPED for {agent_type.value}")

    def is_available(self, agent_type: SubAgentType) -> bool:
        """Check if a sub-agent type is available (not tripped)."""
        tripped = self._tripped_at.get(agent_type)
        if tripped is None:
            return True
        # Auto-reset after interval
        if time.time() - tripped > self.RESET_INTERVAL:
            self._failures.pop(agent_type, None)
            self._tripped_at.pop(agent_type, None)
            logger.info(f"Circuit breaker RESET for {agent_type.value}")
            return True
        return False

    def get_effective_type(self, agent_type: SubAgentType) -> SubAgentType:
        """Return the type to use (falls back to GENERIC if tripped)."""
        if self.is_available(agent_type):
            return agent_type
        return SubAgentType.GENERIC


# ─── Weighted Result Aggregator ─────────────────────────────────────────────

class WeightedAggregator:
    """
    Type-aware result aggregator.

    Tool results are weighted higher (more reliable) than
    pure LLM reasoning. Research results with sources are
    preferred. Failed results are reported separately.
    """

    __slots__ = ()

    @staticmethod
    def aggregate(
        results: list[SubAgentResult],
        goal: str,
    ) -> dict[str, Any]:
        """
        Aggregate sub-agent results with type-aware weighting.

        Returns dict with merged_context, stats, best_result, failed.
        """
        successful = [r for r in results if r.status == SubAgentStatus.COMPLETED]
        failed = [r for r in results if r.status != SubAgentStatus.COMPLETED]

        # Sort by weighted score: relevance * type_weight
        def _sort_key(r: SubAgentResult) -> float:
            return r.relevance_score * _TYPE_WEIGHTS.get(r.agent_type, 0.7)

        successful.sort(key=_sort_key, reverse=True)

        # Build merged context
        parts: list[str] = []
        for r in successful:
            icon = "🟢" if r.relevance_score > 0.5 else "🟡"
            type_tag = r.agent_type.value.upper()
            parts.append(
                f"{icon} [{r.node_id}|{type_tag}] (rel={r.relevance_score:.2f}):\n{r.output}"
            )

        merged = "\n\n".join(parts) if parts else "(нет результатов)"

        total_duration = sum(r.duration_ms for r in results)
        total_tools = sum(r.tool_calls for r in results)
        avg_relevance = (
            sum(r.relevance_score for r in successful) / max(1, len(successful))
        )

        return {
            "merged_context": merged,
            "stats": {
                "total": len(results),
                "successful": len(successful),
                "failed": len(failed),
                "avg_relevance": round(avg_relevance, 3),
                "total_duration_ms": total_duration,
                "total_tool_calls": total_tools,
                "types_used": list({r.agent_type.value for r in results}),
            },
            "best_result": successful[0] if successful else None,
            "failed": failed,
        }


# ─── Work-Stealing Pool ────────────────────────────────────────────────────

class WorkStealingPool:
    """
    Enhanced sub-agent pool with priority execution and circuit breaker.

    Features:
    - Priority: nodes with tools execute first (faster, more reliable)
    - Adaptive concurrency: scale semaphore by task count
    - Circuit breaker: disable failing sub-agent types
    - Per-agent timeout with retry and backoff
    - Structured logging
    """

    def __init__(
        self,
        max_concurrent: int = MAX_CONCURRENT_AGENTS,
        timeout: int = SUB_AGENT_TIMEOUT,
        max_retries: int = MAX_RETRIES,
    ):
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self.max_retries = max_retries
        self._circuit_breaker = CircuitBreaker()
        self._total_executed = 0

    async def execute_parallel(
        self,
        nodes: list[PlanNode],
        goal: str,
        context: str = "",
        completed_results: dict[str, str] | None = None,
    ) -> list[SubAgentResult]:
        """
        Execute nodes in parallel with priority ordering.

        Tool-nodes execute first (fastest). LLM-reasoning nodes
        execute after. All within concurrency limit.
        """
        if not nodes:
            return []

        # Priority sort: tool nodes first (faster, more deterministic)
        sorted_nodes = sorted(nodes, key=lambda n: (0 if n.tool_name else 1, n.id))

        # Adaptive concurrency: more tasks → more parallelism (up to max)
        effective_concurrent = min(self.max_concurrent, max(2, len(sorted_nodes)))
        semaphore = asyncio.Semaphore(effective_concurrent)

        logger.info(
            f"WorkStealingPool: {len(sorted_nodes)} nodes "
            f"(concurrency={effective_concurrent})"
        )

        tasks = []
        for node in sorted_nodes:
            # Create typed sub-agent via factory
            agent = SubAgentFactory.create(
                node=node,
                goal=goal,
                context=context,
                completed_results=completed_results,
            )

            # Apply circuit breaker
            effective_type = self._circuit_breaker.get_effective_type(agent.agent_type)
            if effective_type != agent.agent_type:
                agent.agent_type = effective_type

            tasks.append(self._execute_with_limits(agent, semaphore))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to failed results + update circuit breaker
        final_results: list[SubAgentResult] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                node = sorted_nodes[i]
                node.mark_failed(str(result)[:500])
                final_results.append(SubAgentResult(
                    node_id=node.id,
                    status=SubAgentStatus.FAILED,
                    error=str(result)[:500],
                ))
            else:
                final_results.append(result)
                # Update circuit breaker
                if result.status == SubAgentStatus.COMPLETED:
                    self._circuit_breaker.record_success(result.agent_type)
                else:
                    self._circuit_breaker.record_failure(result.agent_type)

        self._total_executed += len(final_results)
        return final_results

    async def _execute_with_limits(
        self,
        agent: SubAgent,
        semaphore: asyncio.Semaphore,
    ) -> SubAgentResult:
        """Execute one sub-agent with semaphore + timeout + retry."""
        async with semaphore:
            last_error = ""
            for attempt in range(self.max_retries + 1):
                try:
                    result = await asyncio.wait_for(
                        agent.execute(),
                        timeout=self.timeout,
                    )
                    if result.status == SubAgentStatus.COMPLETED:
                        result.retries = attempt
                        return result

                    last_error = result.error or "Unknown"

                except asyncio.TimeoutError:
                    last_error = f"Timeout after {self.timeout}s"
                    agent.node.mark_failed(last_error)

                # Retry logic
                if attempt < self.max_retries:
                    agent.node.status = NodeStatus.PENDING
                    agent.node.retry_count += 1
                    agent.status = SubAgentStatus.IDLE
                    wait = 0.5 * (attempt + 1)
                    logger.warning(
                        f"SubAgent [{agent.node.id}] retry "
                        f"{attempt + 1}/{self.max_retries}: {last_error}"
                    )
                    await asyncio.sleep(wait)

            # All retries exhausted
            return SubAgentResult(
                node_id=agent.node.id,
                status=SubAgentStatus.FAILED,
                error=last_error,
                retries=self.max_retries,
                agent_type=agent.agent_type,
            )

    @property
    def total_executed(self) -> int:
        return self._total_executed


# ─── Backward Compatibility Aliases ─────────────────────────────────────────

# These keep existing code working without changes
SubAgentPool = WorkStealingPool
ResultAggregator = WeightedAggregator

# ─── Global Instances ────────────────────────────────────────────────────────

sub_agent_pool = WorkStealingPool()
result_aggregator = WeightedAggregator()
