"""Task planner — decompose complex goals."""

from __future__ import annotations

from dataclasses import dataclass, field

from pds_ultimate.core.llm.client import llm_client
from pds_ultimate.core.llm.router import TaskKind


@dataclass
class PlanStep:
    id: str
    task: str
    depends_on: list[str] = field(default_factory=list)
    status: str = "pending"  # pending | running | done | failed
    result: str = ""


class Planner:
    async def create_plan(self, goal: str, context: str = "") -> list[PlanStep]:
        data = await llm_client.chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "Разбей цель на 2-8 конкретных шагов. JSON: "
                        '{"steps":[{"id":"1","task":"...","depends_on":[]}]}'
                    ),
                },
                {"role": "user", "content": f"Цель: {goal}\n\nКонтекст:\n{context}"},
            ],
            kind=TaskKind.PLAN,
        )
        steps = []
        for item in data.get("steps", []):
            steps.append(
                PlanStep(
                    id=str(item.get("id", len(steps) + 1)),
                    task=item.get("task", ""),
                    depends_on=[str(d) for d in item.get("depends_on", [])],
                )
            )
        return steps

    def next_runnable(self, steps: list[PlanStep]) -> PlanStep | None:
        done = {s.id for s in steps if s.status == "done"}
        for step in steps:
            if step.status != "pending":
                continue
            if all(dep in done for dep in step.depends_on):
                return step
        return None

    def format_plan(self, steps: list[PlanStep]) -> str:
        lines = []
        for s in steps:
            deps = f" (after: {','.join(s.depends_on)})" if s.depends_on else ""
            lines.append(f"- [{s.status}] {s.id}: {s.task}{deps}")
        return "\n".join(lines)
