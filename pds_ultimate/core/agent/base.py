"""Base agent — state, memory hooks, step limits."""

from __future__ import annotations

from dataclasses import dataclass, field

from pds_ultimate.core.agent.types import AgentResponse, AgentStep
from pds_ultimate.core.memory.hierarchy import hierarchical_memory


@dataclass
class BaseAgent:
    name: str = "Ethan"
    max_steps: int = 40
    steps: list[AgentStep] = field(default_factory=list)

    def reset(self) -> None:
        self.steps.clear()

    def record_step(self, step: AgentStep) -> None:
        self.steps.append(step)

    def remember_turn(self, user_id: int, role: str, content: str) -> None:
        hierarchical_memory.add_turn(user_id, role, content)
