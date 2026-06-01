"""
Тесты Autonomy Engine (Part 8)
==================================
AutonomyEngine, SelfCorrectionEngine, GoalDecomposer, BatchProcessor.
~55 тестов.
"""

import asyncio
from datetime import datetime, timedelta

from pds_ultimate.core.autonomy_engine import (
    AutonomousTask,
    AutonomyEngine,
    BatchProcessor,
    GoalDecomposer,
    SelfCorrectionEngine,
    TaskPriority,
    TaskStatus,
    TaskStep,
    autonomy_engine,
)

# ═══════════════════════════════════════════════════════════════════════════════
# TaskPriority Enum
# ═══════════════════════════════════════════════════════════════════════════════


class TestTaskPriority:
    """Enum TaskPriority — приоритеты задач."""

    def test_critical_highest(self):
        assert TaskPriority.CRITICAL.value == 4

    def test_high(self):
        assert TaskPriority.HIGH.value == 3

    def test_medium(self):
        assert TaskPriority.MEDIUM.value == 2

    def test_low(self):
        assert TaskPriority.LOW.value == 1

    def test_background_lowest(self):
        assert TaskPriority.BACKGROUND.value == 0

    def test_ordering(self):
        assert TaskPriority.CRITICAL > TaskPriority.LOW


# ═══════════════════════════════════════════════════════════════════════════════
# TaskStatus Enum
# ═══════════════════════════════════════════════════════════════════════════════


class TestTaskStatus:
    """Enum TaskStatus — статусы задач."""

    def test_queued(self):
        assert TaskStatus.QUEUED.value == "queued"

    def test_running(self):
        assert TaskStatus.RUNNING.value == "running"

    def test_completed(self):
        assert TaskStatus.COMPLETED.value == "completed"

    def test_failed(self):
        assert TaskStatus.FAILED.value == "failed"

    def test_cancelled(self):
        assert TaskStatus.CANCELLED.value == "cancelled"

    def test_total_statuses(self):
        assert len(TaskStatus) == 10


# ═══════════════════════════════════════════════════════════════════════════════
# TaskStep dataclass
# ═══════════════════════════════════════════════════════════════════════════════


class TestTaskStep:
    """TaskStep — один шаг задачи."""

    def test_create_default(self):
        step = TaskStep()
        assert step.id
        assert step.status == TaskStatus.QUEUED
        assert step.attempts == 0

    def test_can_retry_default(self):
        step = TaskStep(max_attempts=3)
        assert step.can_retry is True

    def test_cannot_retry_after_max(self):
        step = TaskStep(max_attempts=2, attempts=2)
        assert step.can_retry is False

    def test_duration_zero_before_complete(self):
        step = TaskStep()
        assert step.duration_ms == 0

    def test_duration_after_complete(self):
        step = TaskStep(started_at=100.0, completed_at=100.5)
        assert step.duration_ms == 500

    def test_to_dict(self):
        step = TaskStep(description="Тестовый шаг", tool_name="web_search")
        d = step.to_dict()
        assert d["description"] == "Тестовый шаг"
        assert d["tool"] == "web_search"
        assert d["status"] == "queued"


# ═══════════════════════════════════════════════════════════════════════════════
# AutonomousTask dataclass
# ═══════════════════════════════════════════════════════════════════════════════


class TestAutonomousTask:
    """AutonomousTask — автономная задача."""

    def test_create_default(self):
        task = AutonomousTask(title="Test")
        assert task.title == "Test"
        assert task.status == TaskStatus.QUEUED
        assert task.priority == TaskPriority.MEDIUM

    def test_is_terminal_completed(self):
        task = AutonomousTask(status=TaskStatus.COMPLETED)
        assert task.is_terminal is True

    def test_is_terminal_failed(self):
        task = AutonomousTask(status=TaskStatus.FAILED)
        assert task.is_terminal is True

    def test_is_terminal_running(self):
        task = AutonomousTask(status=TaskStatus.RUNNING)
        assert task.is_terminal is False

    def test_is_overdue_no_deadline(self):
        task = AutonomousTask()
        assert task.is_overdue is False

    def test_is_overdue_past_deadline(self):
        task = AutonomousTask(
            deadline=datetime.utcnow() - timedelta(hours=1)
        )
        assert task.is_overdue is True

    def test_is_overdue_future_deadline(self):
        task = AutonomousTask(
            deadline=datetime.utcnow() + timedelta(hours=1)
        )
        assert task.is_overdue is False

    def test_progress_no_steps(self):
        task = AutonomousTask()
        assert task.progress == 0.0

    def test_progress_half(self):
        task = AutonomousTask(steps=[
            TaskStep(status=TaskStatus.COMPLETED),
            TaskStep(status=TaskStatus.QUEUED),
        ])
        assert task.progress == 0.5

    def test_progress_all_done(self):
        task = AutonomousTask(steps=[
            TaskStep(status=TaskStatus.COMPLETED),
            TaskStep(status=TaskStatus.COMPLETED),
        ])
        assert task.progress == 1.0

    def test_to_dict(self):
        task = AutonomousTask(title="Dict Test", tags=["test"])
        d = task.to_dict()
        assert d["title"] == "Dict Test"
        assert d["status"] == "queued"
        assert d["tags"] == ["test"]
        assert "progress" in d


# ═══════════════════════════════════════════════════════════════════════════════
# SelfCorrectionEngine
# ═══════════════════════════════════════════════════════════════════════════════


class TestSelfCorrectionEngine:
    """SelfCorrectionEngine — самокоррекция."""

    def test_analyze_timeout(self):
        engine = SelfCorrectionEngine()
        step = TaskStep(attempts=0, max_attempts=3)
        strategy = engine.analyze_error(step, "Request timeout")
        assert strategy == SelfCorrectionEngine.Strategy.RETRY_SAME

    def test_analyze_rate_limit(self):
        engine = SelfCorrectionEngine()
        step = TaskStep()
        strategy = engine.analyze_error(step, "rate_limit exceeded")
        assert strategy == SelfCorrectionEngine.Strategy.RETRY_SAME

    def test_analyze_not_found(self):
        engine = SelfCorrectionEngine()
        step = TaskStep()
        strategy = engine.analyze_error(step, "Resource not_found")
        assert strategy == SelfCorrectionEngine.Strategy.SKIP

    def test_analyze_permission(self):
        engine = SelfCorrectionEngine()
        step = TaskStep()
        strategy = engine.analyze_error(step, "Permission denied")
        assert strategy == SelfCorrectionEngine.Strategy.ABORT

    def test_analyze_unknown_with_retries(self):
        engine = SelfCorrectionEngine()
        step = TaskStep(attempts=0, max_attempts=3)
        strategy = engine.analyze_error(step, "Some random error")
        assert strategy == SelfCorrectionEngine.Strategy.RETRY_MODIFIED

    def test_analyze_unknown_no_retries(self):
        engine = SelfCorrectionEngine()
        step = TaskStep(attempts=3, max_attempts=3)
        strategy = engine.analyze_error(step, "Some random error")
        assert strategy == SelfCorrectionEngine.Strategy.SKIP

    def test_suggest_modification_timeout(self):
        engine = SelfCorrectionEngine()
        step = TaskStep(tool_params={"timeout": 30})
        mods = engine.suggest_modification(step, "timeout error")
        assert mods.get("timeout", 0) > 30

    def test_suggest_modification_rate_limit(self):
        engine = SelfCorrectionEngine()
        step = TaskStep()
        mods = engine.suggest_modification(step, "rate_limit 429")
        assert mods.get("_delay_seconds", 0) > 0

    def test_correction_message(self):
        engine = SelfCorrectionEngine()
        step = TaskStep(description="Поиск в Google")
        msg = engine.get_correction_message(
            step, SelfCorrectionEngine.Strategy.RETRY_SAME, "timeout"
        )
        assert "Поиск в Google" in msg


# ═══════════════════════════════════════════════════════════════════════════════
# GoalDecomposer
# ═══════════════════════════════════════════════════════════════════════════════


class TestGoalDecomposer:
    """GoalDecomposer — декомпозиция задач."""

    def test_is_complex_short(self):
        decomposer = GoalDecomposer()
        assert decomposer.is_complex("Найди курс доллара") is False

    def test_is_complex_markers(self):
        decomposer = GoalDecomposer()
        assert decomposer.is_complex(
            "Проанализируй все конкурентов и сделай полный отчёт"
        ) is True

    def test_is_complex_long(self):
        decomposer = GoalDecomposer()
        assert decomposer.is_complex("x " * 200) is True

    def test_is_complex_conjunctions(self):
        decomposer = GoalDecomposer()
        assert decomposer.is_complex(
            "Найди информацию, и сравни цены, и составь отчёт, и отправь"
        ) is True

    def test_decompose_search(self):
        decomposer = GoalDecomposer()
        steps = decomposer.decompose("Найди информацию о Python")
        assert len(steps) >= 1
        # Должен найти web_search
        tools = [s.tool_name for s in steps if s.tool_name]
        assert "web_search" in tools

    def test_decompose_translate(self):
        decomposer = GoalDecomposer()
        steps = decomposer.decompose("Переведи текст на английский")
        tools = [s.tool_name for s in steps if s.tool_name]
        assert "translate_text" in tools

    def test_decompose_exchange(self):
        decomposer = GoalDecomposer()
        steps = decomposer.decompose("Курс доллара к манату")
        tools = [s.tool_name for s in steps if s.tool_name]
        assert "exchange_rates" in tools

    def test_decompose_generic(self):
        """Если ничего не определили — 3 generic шага."""
        decomposer = GoalDecomposer()
        steps = decomposer.decompose("Сделай что-нибудь абстрактное xyz")
        assert len(steps) == 3

    def test_decompose_with_available_tools(self):
        decomposer = GoalDecomposer()
        steps = decomposer.decompose(
            "Найди и переведи",
            available_tools=["web_search"],
        )
        tools = [s.tool_name for s in steps if s.tool_name]
        assert "translate_text" not in tools


# ═══════════════════════════════════════════════════════════════════════════════
# BatchProcessor
# ═══════════════════════════════════════════════════════════════════════════════


class TestBatchProcessor:
    """BatchProcessor — параллельная обработка."""

    def test_group_by_tool(self):
        bp = BatchProcessor()
        steps = [
            TaskStep(tool_name="web_search"),
            TaskStep(tool_name="web_search"),
            TaskStep(tool_name="translate_text"),
        ]
        groups = bp.group_by_tool(steps)
        assert "web_search" in groups
        assert len(groups["web_search"]) == 2
        assert "translate_text" in groups

    def test_find_independent_all(self):
        bp = BatchProcessor()
        steps = [
            TaskStep(tool_name="web_search"),
            TaskStep(tool_name="translate_text"),
        ]
        ind, dep = bp.find_independent(steps)
        assert len(ind) == 2
        assert len(dep) == 0

    def test_find_independent_with_refs(self):
        bp = BatchProcessor()
        steps = [
            TaskStep(tool_name="web_search"),
            TaskStep(tool_name="translate", tool_params={"text": "${result}"}),
        ]
        ind, dep = bp.find_independent(steps)
        assert len(dep) >= 1

    def test_execute_parallel(self):
        bp = BatchProcessor()
        steps = [
            TaskStep(description="Step 1"),
            TaskStep(description="Step 2"),
        ]

        async def executor(step):
            step.status = TaskStatus.COMPLETED
            step.result = "OK"
            return step

        results = asyncio.get_event_loop().run_until_complete(
            bp.execute_parallel(steps, executor)
        )
        assert len(results) == 2
        assert all(r.status == TaskStatus.COMPLETED for r in results)


# ═══════════════════════════════════════════════════════════════════════════════
# AutonomyEngine
# ═══════════════════════════════════════════════════════════════════════════════


class TestAutonomyEngine:
    """AutonomyEngine — центральный движок."""

    def _make_engine(self) -> AutonomyEngine:
        engine = AutonomyEngine()
        engine._tasks.clear()
        engine._task_queue.clear()
        return engine

    def test_create_task(self):
        engine = self._make_engine()
        task = engine.create_task(title="Тест", description="Описание")
        assert task.id
        assert task.title == "Тест"
        assert task.status == TaskStatus.QUEUED

    def test_create_task_with_priority(self):
        engine = self._make_engine()
        task = engine.create_task(
            title="Urgent", priority=TaskPriority.CRITICAL
        )
        assert task.priority == TaskPriority.CRITICAL

    def test_create_task_with_deadline(self):
        engine = self._make_engine()
        dl = datetime.utcnow() + timedelta(hours=2)
        task = engine.create_task(title="Deadline", deadline=dl)
        assert task.deadline == dl

    def test_cancel_task(self):
        engine = self._make_engine()
        task = engine.create_task(title="Cancel me")
        assert engine.cancel_task(task.id) is True
        assert task.status == TaskStatus.CANCELLED

    def test_cancel_nonexistent(self):
        engine = self._make_engine()
        assert engine.cancel_task("nonexistent") is False

    def test_cancel_terminal(self):
        engine = self._make_engine()
        task = engine.create_task(title="Done")
        task.status = TaskStatus.COMPLETED
        assert engine.cancel_task(task.id) is False

    def test_get_task(self):
        engine = self._make_engine()
        task = engine.create_task(title="Find me")
        found = engine.get_task(task.id)
        assert found is not None
        assert found.title == "Find me"

    def test_get_task_nonexistent(self):
        engine = self._make_engine()
        assert engine.get_task("nope") is None

    def test_get_user_tasks(self):
        engine = self._make_engine()
        engine.create_task(title="T1", owner_id=1)
        engine.create_task(title="T2", owner_id=1)
        engine.create_task(title="T3", owner_id=2)
        assert len(engine.get_user_tasks(1)) == 2
        assert len(engine.get_user_tasks(2)) == 1

    def test_total_tasks(self):
        engine = self._make_engine()
        engine.create_task(title="T1")
        engine.create_task(title="T2")
        assert engine.total_tasks == 2

    def test_active_tasks_count(self):
        engine = self._make_engine()
        engine.create_task(title="Active")
        t2 = engine.create_task(title="Done")
        t2.status = TaskStatus.COMPLETED
        assert engine.active_tasks_count == 1

    def test_queue_size(self):
        engine = self._make_engine()
        engine.create_task(title="Q1")
        engine.create_task(title="Q2")
        assert engine.queue_size == 2

    def test_decompose_task(self):
        engine = self._make_engine()
        task = engine.create_task(title="Найди курс доллара")
        engine.decompose_task(task)
        assert len(task.steps) >= 1
        assert task.status == TaskStatus.READY

    def test_get_stats(self):
        engine = self._make_engine()
        engine.create_task(title="S1")
        stats = engine.get_stats()
        assert stats["total"] == 1
        assert "by_priority" in stats

    def test_format_queue_empty(self):
        engine = self._make_engine()
        text = engine.format_queue()
        assert "пуста" in text.lower()

    def test_format_queue_with_tasks(self):
        engine = self._make_engine()
        engine.create_task(title="Задача 1")
        text = engine.format_queue()
        assert "Задача 1" in text

    def test_priority_ordering_in_queue(self):
        engine = self._make_engine()
        low = engine.create_task(title="Low", priority=TaskPriority.LOW)
        high = engine.create_task(title="High", priority=TaskPriority.HIGH)
        # High should be before Low in queue
        assert engine._task_queue.index(
            high.id) < engine._task_queue.index(low.id)

    def test_execute_task_simple(self):
        """Выполнение простой задачи (без инструментов)."""
        engine = self._make_engine()
        task = engine.create_task(title="Simple")
        task.steps = [
            TaskStep(description="Step 1"),
            TaskStep(description="Step 2"),
        ]
        task.status = TaskStatus.READY

        async def mock_executor(tool_name, params):
            return type("R", (), {"success": True, "output": "OK", "error": ""})()

        result = asyncio.get_event_loop().run_until_complete(
            engine.execute_task(task, mock_executor)
        )
        assert result.status == TaskStatus.COMPLETED

    def test_set_progress_callback(self):
        engine = self._make_engine()
        task = engine.create_task(title="CB")
        callback_called = []

        async def cb(t):
            callback_called.append(t.id)

        engine.set_progress_callback(task.id, cb)
        assert task.id in engine._callbacks


# ═══════════════════════════════════════════════════════════════════════════════
# Global instance
# ═══════════════════════════════════════════════════════════════════════════════


class TestAutonomyEngineGlobal:
    """Глобальный экземпляр."""

    def test_global_exists(self):
        assert autonomy_engine is not None
        assert isinstance(autonomy_engine, AutonomyEngine)
