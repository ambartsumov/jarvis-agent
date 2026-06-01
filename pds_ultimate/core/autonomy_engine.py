"""Compatibility shim for /tasks command."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AutonomyTask:
    id: str
    goal: str
    status: str = "pending"


class AutonomyEngine:
    def __init__(self) -> None:
        self._tasks: dict[str, AutonomyTask] = {}

    def get_task(self, task_id: str) -> AutonomyTask | None:
        return self._tasks.get(task_id)

    def get_stats(self) -> dict:
        return {"total": len(self._tasks), "pending": 0, "running": 0, "done": 0}

    def format_queue(self) -> str:
        if not self._tasks:
            return "Очередь пуста."
        return "\n".join(f"- [{t.status}] {t.id}: {t.goal}" for t in self._tasks.values())


autonomy_engine = AutonomyEngine()
