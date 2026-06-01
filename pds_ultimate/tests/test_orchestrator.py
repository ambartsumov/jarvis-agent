"""Tests for the DAG orchestrator (sub-agent decomposition)."""

from __future__ import annotations

import pytest

from pds_ultimate.core.agent.orchestrator import DAGExecutor
from pds_ultimate.core.agent.planner import PlanStep


class _FakePlanner:
    def __init__(self, steps):
        self._steps = steps

    async def create_plan(self, goal, context=""):
        return [PlanStep(id=s[0], task=s[1], depends_on=s[2]) for s in self._steps]


@pytest.mark.asyncio
class TestDAGExecutor:
    async def test_runs_all_steps(self):
        planner = _FakePlanner([("1", "do A", []), ("2", "do B", ["1"])])
        ex = DAGExecutor(planner)
        order = []

        async def runner(task, ctx):
            order.append(task)
            return f"done:{task}"

        summary, steps = await ex.execute("goal", runner)
        assert len(steps) == 2
        assert all(s.status == "done" for s in steps)
        assert order == ["do A", "do B"]  # dependency order respected

    async def test_dependency_context_passed(self):
        planner = _FakePlanner([("1", "produce X", []), ("2", "use X", ["1"])])
        ex = DAGExecutor(planner)
        seen_ctx = {}

        async def runner(task, ctx):
            seen_ctx[task] = ctx
            return "RESULT_X" if task == "produce X" else "ok"

        await ex.execute("goal", runner)
        assert "RESULT_X" in seen_ctx["use X"]

    async def test_parallel_independent_steps(self):
        planner = _FakePlanner([("1", "A", []), ("2", "B", []), ("3", "C", [])])
        ex = DAGExecutor(planner, max_parallel=3)

        async def runner(task, ctx):
            return task

        summary, steps = await ex.execute("goal", runner)
        assert all(s.status == "done" for s in steps)

    async def test_empty_plan_falls_back_to_direct(self):
        planner = _FakePlanner([])
        ex = DAGExecutor(planner)

        async def runner(task, ctx):
            return "direct answer"

        summary, steps = await ex.execute("simple goal", runner)
        assert summary == "direct answer" and steps == []

    async def test_cycle_does_not_hang(self):
        planner = _FakePlanner([("1", "A", ["2"]), ("2", "B", ["1"])])
        ex = DAGExecutor(planner)

        async def runner(task, ctx):
            return "x"

        summary, steps = await ex.execute("goal", runner)
        # Should terminate; cyclic steps remain pending, not done
        assert any(s.status == "pending" for s in steps)
