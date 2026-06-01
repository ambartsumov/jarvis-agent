"""DAG task orchestrator — decompose a goal and run sub-agents respecting dependencies."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from pds_ultimate.config import logger
from pds_ultimate.core.agent.planner import Planner, PlanStep

# A sub-runner takes (subtask, context) and returns the textual result.
SubRunner = Callable[[str, str], Awaitable[str]]


class DAGExecutor:
    """
    Executes a plan as a dependency DAG:
    - independent steps run in parallel (one sub-agent each)
    - dependent steps receive their predecessors' results as context
    - bounded by max_parallel to avoid resource/token blow-ups
    """

    def __init__(self, planner: Planner | None = None, *, max_parallel: int = 3) -> None:
        self.planner = planner or Planner()
        self.max_parallel = max_parallel

    async def execute(
        self,
        goal: str,
        sub_runner: SubRunner,
        *,
        context: str = "",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[str, list[PlanStep]]:
        steps = await self.planner.create_plan(goal, context)
        if not steps:
            result = await sub_runner(goal, context)
            return result, []

        results: dict[str, str] = {}
        sem = asyncio.Semaphore(self.max_parallel)

        async def run_step(step: PlanStep) -> None:
            async with sem:
                dep_ctx = "\n".join(
                    f"[Результат шага {d}]: {results.get(d, '')[:1500]}" for d in step.depends_on
                )
                full_ctx = (context + "\n" + dep_ctx).strip()
                step.status = "running"
                if on_progress:
                    await on_progress(f"▶ Шаг {step.id}: {step.task[:80]}")
                try:
                    step.result = await sub_runner(step.task, full_ctx)
                    step.status = "done"
                except Exception as exc:
                    step.result = f"ERROR: {exc}"
                    step.status = "failed"
                    logger.warning(f"DAG step {step.id} failed: {exc}")
                results[step.id] = step.result

        # Wave-based execution: each wave = all currently-runnable steps
        guard = 0
        while any(s.status == "pending" for s in steps) and guard < len(steps) + 2:
            guard += 1
            done_ids = {s.id for s in steps if s.status == "done"}
            wave = [
                s for s in steps
                if s.status == "pending" and all(d in done_ids for d in s.depends_on)
            ]
            if not wave:
                # Unsatisfiable dependencies (cycle / failed dep) — stop
                break
            await asyncio.gather(*(run_step(s) for s in wave))

        summary = "\n\n".join(
            f"### Шаг {s.id}: {s.task}\n[{s.status}] {s.result[:1200]}" for s in steps
        )
        return summary, steps


dag_executor = DAGExecutor()
