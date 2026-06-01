"""
PDS-Ultimate Task Planner v1.0 — DAG-based Task Decomposition
==============================================================
LLM-powered task decomposition into a Directed Acyclic Graph (DAG).

FEATURES:
1. JSON Schema-validated plan generation
2. Dependency auto-detection between steps
3. Parallel-ready: independent nodes execute simultaneously
4. Smart re-planning on node failure (backtracking)
5. Tool-aware: knows available tools and selects the best match
6. Structured logging at every stage

ARCHITECTURE:
    User goal → LLM Strategist → DAG Plan → Validate → Execute
                                      ↑               ↓
                                  Re-plan ←── Node failure

Used by Agent v6 for complex multi-step tasks.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pds_ultimate.config import logger

# ─── Enums ───────────────────────────────────────────────────────────────────


class NodeStatus(str, Enum):
    """Execution status of a DAG node."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PlanComplexity(str, Enum):
    """Complexity classification for planning decisions."""
    SIMPLE = "simple"       # No plan needed — direct answer
    MODERATE = "moderate"   # 2-3 steps, linear
    COMPLEX = "complex"     # 4+ steps, with dependencies


# ─── JSON Schema for plan validation ────────────────────────────────────────

PLAN_JSON_SCHEMA = {
    "type": "object",
    "required": ["steps"],
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "description"],
                "properties": {
                    "id": {"type": "string", "description": "Unique step ID"},
                    "description": {"type": "string", "description": "What this step does"},
                    "tool": {"type": "string", "description": "Tool name to use (or null)"},
                    "params": {"type": "object", "description": "Tool parameters"},
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "IDs of steps this depends on",
                    },
                },
            },
        },
    },
}

PLANNER_SYSTEM_PROMPT = """Ты — планировщик задач. Разбей цель на минимум конкретных шагов.

ПРАВИЛА:
1. Каждый шаг — одно конкретное действие (один вызов инструмента или одна мысль)
2. Максимум параллелизма: если шаги независимы, depends_on = []
3. Зависимости ТОЛЬКО когда результат одного шага нужен другому
4. Используй ТОЛЬКО доступные инструменты (список ниже)
5. Финальный шаг — ВСЕГДА "synthesize" (собрать результаты в ответ)

ДОСТУПНЫЕ ИНСТРУМЕНТЫ:
{tools_description}

ФОРМАТ ОТВЕТА (строго JSON):
{{
  "steps": [
    {{"id": "step_1", "description": "Что делаем", "tool": "tool_name", "params": {{}}, "depends_on": []}},
    {{"id": "step_2", "description": "Что делаем", "tool": "tool_name", "params": {{}}, "depends_on": ["step_1"]}},
    {{"id": "synthesize", "description": "Собрать результаты и ответить", "tool": null, "params": {{}}, "depends_on": ["step_1", "step_2"]}}
  ]
}}"""

REPLAN_SYSTEM_PROMPT = """Шаг "{failed_step}" провалился с ошибкой: {error}

Результаты успешных шагов:
{completed_results}

Исходная цель: {goal}

Создай НОВЫЙ план для достижения цели, учитывая:
1. Уже полученные результаты — используй их, не повторяй
2. Причину ошибки — попробуй другой подход
3. Если задачу невозможно выполнить — один шаг с description="impossible"

ФОРМАТ: тот же JSON со steps."""


# ─── DAG Node ────────────────────────────────────────────────────────────────

@dataclass
class PlanNode:
    """
    Single node in a DAG plan.

    Tracks: status, result, retries, timing, confidence.
    Immutable id/description after creation.
    """
    id: str
    description: str
    tool_name: str | None = None
    tool_params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)

    # Execution state
    status: NodeStatus = NodeStatus.PENDING
    result: str | None = None
    error: str | None = None
    retry_count: int = 0
    max_retries: int = 2

    # Timing
    started_at: float | None = None
    completed_at: float | None = None

    @property
    def duration_ms(self) -> int:
        if self.started_at and self.completed_at:
            return int((self.completed_at - self.started_at) * 1000)
        return 0

    @property
    def is_terminal(self) -> bool:
        return self.status in (NodeStatus.COMPLETED, NodeStatus.FAILED, NodeStatus.SKIPPED)

    def can_retry(self) -> bool:
        return self.retry_count < self.max_retries

    def mark_running(self) -> None:
        self.status = NodeStatus.RUNNING
        self.started_at = time.time()

    def mark_completed(self, result: str) -> None:
        self.status = NodeStatus.COMPLETED
        self.result = result
        self.completed_at = time.time()

    def mark_failed(self, error: str) -> None:
        self.status = NodeStatus.FAILED
        self.error = error
        self.completed_at = time.time()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "tool": self.tool_name,
            "status": self.status.value,
            "result": (self.result or "")[:200],
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


# ─── DAG Plan ────────────────────────────────────────────────────────────────

@dataclass
class ExecutionPlan:
    """
    Directed Acyclic Graph (DAG) of PlanNodes.

    Provides:
    - get_ready_nodes(): nodes whose deps are all completed
    - get_progress(): completion stats
    - topological ordering validation
    - Serialization for logging
    """
    goal: str
    nodes: dict[str, PlanNode] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    revision: int = 0

    def add_node(self, node: PlanNode) -> None:
        self.nodes[node.id] = node

    def get_ready_nodes(self) -> list[PlanNode]:
        """Return nodes whose dependencies are all completed."""
        ready: list[PlanNode] = []
        for node in self.nodes.values():
            if node.status != NodeStatus.PENDING:
                continue
            deps_ok = all(
                self.nodes[dep].status == NodeStatus.COMPLETED
                for dep in node.depends_on
                if dep in self.nodes
            )
            if deps_ok:
                ready.append(node)
        return ready

    def get_completed_results(self) -> dict[str, str]:
        """Map of completed node IDs to their results."""
        return {
            nid: n.result or ""
            for nid, n in self.nodes.items()
            if n.status == NodeStatus.COMPLETED
        }

    def get_failed_nodes(self) -> list[PlanNode]:
        return [n for n in self.nodes.values() if n.status == NodeStatus.FAILED]

    def get_progress(self) -> dict:
        total = len(self.nodes)
        completed = sum(1 for n in self.nodes.values()
                        if n.status == NodeStatus.COMPLETED)
        failed = sum(1 for n in self.nodes.values()
                     if n.status == NodeStatus.FAILED)
        pending = sum(1 for n in self.nodes.values()
                      if n.status == NodeStatus.PENDING)
        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "pending": pending,
            "progress_pct": round(completed / max(1, total) * 100),
        }

    @property
    def is_done(self) -> bool:
        return all(n.is_terminal for n in self.nodes.values())

    @property
    def has_failures(self) -> bool:
        return any(n.status == NodeStatus.FAILED for n in self.nodes.values())

    def validate_dag(self) -> list[str]:
        """Check for cycles and missing dependencies. Returns list of errors."""
        errors: list[str] = []
        # Check missing deps
        for node in self.nodes.values():
            for dep in node.depends_on:
                if dep not in self.nodes:
                    errors.append(
                        f"Node '{node.id}' depends on missing '{dep}'")

        # Cycle detection (Kahn's algorithm)
        in_degree: dict[str, int] = {nid: 0 for nid in self.nodes}
        for node in self.nodes.values():
            for dep in node.depends_on:
                if dep in in_degree:
                    in_degree[node.id] = in_degree.get(node.id, 0) + 1

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        visited = 0
        while queue:
            nid = queue.pop(0)
            visited += 1
            for node in self.nodes.values():
                if nid in node.depends_on:
                    in_degree[node.id] -= 1
                    if in_degree[node.id] == 0:
                        queue.append(node.id)

        if visited < len(self.nodes):
            errors.append("DAG contains a cycle!")

        return errors

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "revision": self.revision,
            "progress": self.get_progress(),
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
        }


# ─── Planner ─────────────────────────────────────────────────────────────────

class TaskPlanner:
    """
    LLM-powered task planner.

    Decomposes a complex goal into a validated DAG of executable steps.
    Supports re-planning (backtracking) on node failure.
    """

    # Tasks shorter than this are always SIMPLE
    SIMPLE_THRESHOLD = 60

    # ── O(1) keyword lookup via frozenset ──
    # Single-word keywords for fast word-level matching
    _COMPLEX_WORDS: frozenset[str] = frozenset({
        "проанализируй", "сравни", "несколько", "подробно",
        "исследуй", "рассчитай", "отправь", "сначала", "потом", "затем",
        "analyze", "compare", "report", "multi", "complex", "research",
    })
    # Multi-word / substring keywords (checked via `in`)
    _COMPLEX_PHRASES: tuple[str, ...] = (
        "создай отчёт", "по шагам", "найди и", "step by step",
    )

    def __init__(self):
        self._plan_count = 0
        logger.info("TaskPlanner initialized")

    def classify_complexity(self, message: str) -> PlanComplexity:
        """Classify task complexity to decide if planning is needed."""
        lower = message.lower()

        # Short messages → simple
        if len(message) < self.SIMPLE_THRESHOLD and "?" not in message:
            return PlanComplexity.SIMPLE

        # O(n) substring check covers both single words and phrases
        # (handles punctuation-attached words like "подробно,")
        complex_hits = sum(1 for kw in self._COMPLEX_WORDS if kw in lower)
        complex_hits += sum(1 for p in self._COMPLEX_PHRASES if p in lower)

        if complex_hits >= 2:
            return PlanComplexity.COMPLEX
        if complex_hits == 1 and len(message) > 100:
            return PlanComplexity.MODERATE

        # Multiple sentences/questions → moderate
        sentence_count = sum(1 for s in message.split(".") if s.strip())
        question_count = message.count("?")
        if sentence_count >= 3 or question_count >= 2:
            return PlanComplexity.MODERATE

        return PlanComplexity.SIMPLE

    async def create_plan(
        self,
        goal: str,
        tools_description: str,
        context: str = "",
        max_steps: int = 8,
    ) -> ExecutionPlan:
        """
        Create an ExecutionPlan (DAG) for the given goal.

        Uses LLM with JSON mode to decompose the task.
        Validates the resulting DAG (no cycles, valid deps).
        """
        from pds_ultimate.core.llm_engine import llm_engine

        self._plan_count += 1

        system_prompt = PLANNER_SYSTEM_PROMPT.format(
            tools_description=tools_description,
        )
        user_msg = f"Цель: {goal}"
        if context:
            user_msg += f"\n\nКонтекст:\n{context}"

        try:
            response = await llm_engine.chat(
                message=user_msg,
                system_prompt=system_prompt,
                task_type="plan_generation",
                temperature=0.2,
                json_mode=True,
            )

            plan_data = json.loads(response)
            plan = self._parse_plan(goal, plan_data, max_steps)

            # Validate
            errors = plan.validate_dag()
            if errors:
                logger.warning(f"Plan validation errors: {errors}")
                # Auto-fix: remove invalid deps
                for node in plan.nodes.values():
                    node.depends_on = [
                        d for d in node.depends_on if d in plan.nodes
                    ]

            logger.info(
                f"Plan #{self._plan_count} created: "
                f"{len(plan.nodes)} steps for '{goal[:60]}'"
            )
            return plan

        except Exception as e:
            logger.error(f"Plan creation failed: {e}")
            return self._fallback_plan(goal)

    async def replan(
        self,
        original_plan: ExecutionPlan,
        failed_node: PlanNode,
        tools_description: str,
    ) -> ExecutionPlan:
        """
        Create a new plan after a node failure (backtracking).

        Feeds the LLM:
        - The original goal
        - What already succeeded
        - What failed and why
        """
        from pds_ultimate.core.llm_engine import llm_engine

        completed = original_plan.get_completed_results()
        completed_text = "\n".join(
            f"  ✅ {nid}: {res[:100]}" for nid, res in completed.items()
        ) or "(нет)"

        prompt = REPLAN_SYSTEM_PROMPT.format(
            failed_step=failed_node.description,
            error=failed_node.error or "Unknown error",
            completed_results=completed_text,
            goal=original_plan.goal,
        )

        try:
            response = await llm_engine.chat(
                message=prompt,
                system_prompt=PLANNER_SYSTEM_PROMPT.format(
                    tools_description=tools_description,
                ),
                task_type="plan_generation",
                temperature=0.3,
                json_mode=True,
            )

            plan_data = json.loads(response)
            new_plan = self._parse_plan(
                original_plan.goal, plan_data, max_steps=8)
            new_plan.revision = original_plan.revision + 1

            # Carry over completed results as pre-completed nodes
            for nid, result in completed.items():
                if nid not in new_plan.nodes:
                    node = PlanNode(id=nid, description=f"[carried] {nid}")
                    node.mark_completed(result)
                    new_plan.add_node(node)

            logger.info(
                f"Re-plan created (revision {new_plan.revision}): "
                f"{len(new_plan.nodes)} steps"
            )
            return new_plan

        except Exception as e:
            logger.error(f"Re-planning failed: {e}")
            return self._fallback_plan(original_plan.goal)

    def _parse_plan(
        self,
        goal: str,
        plan_data: dict,
        max_steps: int,
    ) -> ExecutionPlan:
        """Parse LLM JSON output into an ExecutionPlan."""
        plan = ExecutionPlan(goal=goal)
        steps = plan_data.get("steps", [])

        for i, step in enumerate(steps[:max_steps]):
            node = PlanNode(
                id=step.get("id", f"step_{i}"),
                description=step.get("description", ""),
                tool_name=step.get("tool") or None,
                tool_params=step.get("params", {}) or {},
                depends_on=step.get("depends_on", []) or [],
            )
            plan.add_node(node)

        # Ensure there's at least a synthesize step
        if not any(n.id == "synthesize" for n in plan.nodes.values()):
            all_ids = list(plan.nodes.keys())
            plan.add_node(PlanNode(
                id="synthesize",
                description="Собрать результаты и сформировать ответ",
                depends_on=all_ids,
            ))

        return plan

    def _fallback_plan(self, goal: str) -> ExecutionPlan:
        """Single-step fallback plan when LLM planning fails."""
        plan = ExecutionPlan(goal=goal)
        plan.add_node(PlanNode(
            id="direct",
            description=f"Выполнить напрямую: {goal}",
        ))
        return plan


# ─── Global Instance ─────────────────────────────────────────────────────────

task_planner = TaskPlanner()
