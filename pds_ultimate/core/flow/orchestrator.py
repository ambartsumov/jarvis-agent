"""Flow orchestrator — structured multi-step execution (OpenManus Flow mode)."""

from __future__ import annotations

from pds_ultimate.core.agent.ethan import EthanAgent
from pds_ultimate.core.agent.planner import Planner
from pds_ultimate.core.agent.types import AgentResponse


class FlowOrchestrator:
    """Plan-first mode: decompose → execute each step → synthesize."""

    def __init__(self) -> None:
        self.planner = Planner()
        self.agent = EthanAgent()

    async def run(self, user_id: int, goal: str) -> AgentResponse:
        plan = await self.planner.create_plan(goal)
        step_results: list[str] = []

        for step in plan:
            step.status = "running"
            sub = await self.agent.run(
                user_id,
                f"Шаг {step.id}: {step.task}\n\nКонтекст плана:\n" + self.planner.format_plan(plan),
            )
            step.result = sub.answer
            step.status = "done" if sub.answer else "failed"
            step_results.append(f"Step {step.id}: {sub.answer}")

        synthesis = await self.agent.run(
            user_id,
            "Собери финальный ответ по результатам плана:\n" + "\n".join(step_results),
        )
        synthesis.plan_used = True  # type: ignore[attr-defined]
        return synthesis


flow = FlowOrchestrator()
