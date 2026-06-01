"""Agent data types."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentStep:
    iteration: int
    thought: str = ""
    action: str = ""
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    observation: str = ""
    duration_ms: int = 0


@dataclass
class AgentResponse:
    answer: str
    steps: list[AgentStep] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    verified: bool = True
    total_iterations: int = 0
    total_time_ms: int = 0
    memory_entries_created: int = 0
    plan_used: bool = False
    files_to_send: list[dict] = field(default_factory=list)
    artifacts: list[dict] = field(default_factory=list)
