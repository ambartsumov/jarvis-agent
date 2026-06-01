"""DAG executor — parallel task execution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Awaitable, Callable


@dataclass
class DAGNode:
    id: str
    task: str
    depends_on: list[str] = field(default_factory=list)
    result: str = ""
    error: str = ""


class DAGExecutor:
    async def run(
        self,
        nodes: list[DAGNode],
        worker: Callable[[DAGNode], Awaitable[str]],
        *,
        max_parallel: int = 4,
    ) -> list[DAGNode]:
        pending = {n.id: n for n in nodes}
        completed: set[str] = set()
        lock = asyncio.Lock()

        async def run_node(node: DAGNode) -> None:
            try:
                node.result = await worker(node)
            except Exception as exc:
                node.error = str(exc)
            async with lock:
                completed.add(node.id)

        while len(completed) < len(pending):
            ready = [
                n
                for n in pending.values()
                if n.id not in completed
                and all(d in completed for d in n.depends_on)
                and not n.result
                and not n.error
            ]
            if not ready:
                # Deadlock or all running — wait a bit
                await asyncio.sleep(0.05)
                if not any(n.id not in completed for n in pending.values()):
                    break
                # Force break if circular deps
                stuck = [n for n in pending.values() if n.id not in completed]
                for n in stuck:
                    n.error = n.error or "Blocked by dependencies"
                    completed.add(n.id)
                break

            batch = ready[:max_parallel]
            await asyncio.gather(*(run_node(n) for n in batch))

        return list(pending.values())
