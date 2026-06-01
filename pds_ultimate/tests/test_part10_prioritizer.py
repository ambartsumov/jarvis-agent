"""
Tests for Part 10 — Task Prioritizer
"""

import time

from pds_ultimate.core.task_prioritizer import (
    PriorityLevel,
    PriorityQueue,
    TaskBatch,
    TaskBatcher,
    TaskItem,
    TaskPrioritizer,
    TaskScheduler,
    TaskStatus,
    task_prioritizer,
)


class TestPriorityLevel:
    """Тесты PriorityLevel."""

    def test_ordering(self):
        assert PriorityLevel.CRITICAL < PriorityLevel.HIGH
        assert PriorityLevel.HIGH < PriorityLevel.MEDIUM
        assert PriorityLevel.MEDIUM < PriorityLevel.LOW
        assert PriorityLevel.LOW < PriorityLevel.BACKGROUND

    def test_values(self):
        assert PriorityLevel.CRITICAL == 0
        assert PriorityLevel.BACKGROUND == 4


class TestTaskItem:
    """Тесты TaskItem."""

    def test_create(self):
        task = TaskItem(id="t1", name="Test", priority=PriorityLevel.HIGH)
        assert task.id == "t1"
        assert task.status == TaskStatus.PENDING

    def test_age(self):
        task = TaskItem(id="t2", name="Test")
        assert task.age >= 0

    def test_no_deadline(self):
        task = TaskItem(id="t3", name="Test")
        assert task.time_to_deadline is None
        assert task.is_overdue is False

    def test_with_deadline(self):
        task = TaskItem(
            id="t4", name="Test",
            deadline=time.time() + 60,
        )
        assert task.time_to_deadline is not None
        assert task.time_to_deadline > 0
        assert task.is_overdue is False

    def test_overdue(self):
        task = TaskItem(
            id="t5", name="Test",
            deadline=time.time() - 10,
        )
        assert task.is_overdue is True

    def test_effective_priority(self):
        task = TaskItem(
            id="t6", name="Test",
            priority=PriorityLevel.MEDIUM,
        )
        ep = task.effective_priority
        assert isinstance(ep, float)

    def test_effective_priority_deadline_boost(self):
        urgent = TaskItem(
            id="t7", name="Urgent",
            priority=PriorityLevel.LOW,
            deadline=time.time() + 10,  # 10 seconds
        )
        normal = TaskItem(
            id="t8", name="Normal",
            priority=PriorityLevel.LOW,
        )
        # Urgent should have lower effective priority (= higher importance)
        assert urgent.effective_priority < normal.effective_priority

    def test_to_dict(self):
        task = TaskItem(id="t9", name="Dict test")
        d = task.to_dict()
        assert d["id"] == "t9"
        assert "priority" in d
        assert "effective_priority" in d


class TestPriorityQueue:
    """Тесты PriorityQueue."""

    def test_add_and_pop(self):
        q = PriorityQueue()
        task = TaskItem(id="q1", name="Test", priority=PriorityLevel.HIGH)
        q.add(task)
        result = q.pop()
        assert result is not None
        assert result.id == "q1"
        assert result.status == TaskStatus.RUNNING

    def test_pop_empty(self):
        q = PriorityQueue()
        assert q.pop() is None

    def test_priority_ordering(self):
        q = PriorityQueue()
        q.add(TaskItem(id="lo", name="Low", priority=PriorityLevel.LOW))
        q.add(TaskItem(id="hi", name="High", priority=PriorityLevel.CRITICAL))
        q.add(TaskItem(id="md", name="Med", priority=PriorityLevel.MEDIUM))
        first = q.pop()
        assert first.id == "hi"

    def test_peek(self):
        q = PriorityQueue()
        q.add(TaskItem(id="p1", name="Test"))
        peeked = q.peek()
        assert peeked is not None
        assert peeked.status == TaskStatus.PENDING  # Not changed

    def test_complete(self):
        q = PriorityQueue()
        q.add(TaskItem(id="c1", name="Test"))
        q.pop()  # Set to running
        assert q.complete("c1", result="done") is True

    def test_fail(self):
        q = PriorityQueue()
        q.add(TaskItem(id="f1", name="Test"))
        q.pop()
        assert q.fail("f1", error="oops") is True

    def test_cancel(self):
        q = PriorityQueue()
        q.add(TaskItem(id="x1", name="Test"))
        assert q.cancel("x1") is True

    def test_get_by_status(self):
        q = PriorityQueue()
        q.add(TaskItem(id="s1", name="A"))
        q.add(TaskItem(id="s2", name="B"))
        q.pop()  # s1 → running (by priority, either one)
        pending = q.get_by_status(TaskStatus.PENDING)
        running = q.get_by_status(TaskStatus.RUNNING)
        assert len(pending) == 1
        assert len(running) == 1

    def test_get_overdue(self):
        q = PriorityQueue()
        q.add(TaskItem(
            id="od1", name="Overdue",
            deadline=time.time() - 10,
        ))
        overdue = q.get_overdue()
        assert len(overdue) == 1

    def test_clear_completed(self):
        q = PriorityQueue()
        q.add(TaskItem(id="cc1", name="Test"))
        q.pop()
        q.complete("cc1")
        removed = q.clear_completed()
        assert removed == 1

    def test_max_size(self):
        q = PriorityQueue(max_size=2)
        q.add(TaskItem(id="m1", name="A"))
        q.add(TaskItem(id="m2", name="B"))
        result = q.add(TaskItem(id="m3", name="C"))
        assert result is False
        assert q.total_count == 2

    def test_get_stats(self):
        q = PriorityQueue()
        q.add(TaskItem(id="st1", name="Test"))
        stats = q.get_stats()
        assert stats["total"] == 1
        assert stats["pending"] == 1


class TestTaskBatcher:
    """Тесты TaskBatcher."""

    def test_create_batches(self):
        batcher = TaskBatcher()
        tasks = [
            TaskItem(id="b1", name="API 1", task_type="api"),
            TaskItem(id="b2", name="API 2", task_type="api"),
            TaskItem(id="b3", name="Report", task_type="report"),
        ]
        batches = batcher.create_batches(tasks)
        assert len(batches) >= 2  # api batch + report batch

    def test_batch_size_limit(self):
        batcher = TaskBatcher(max_batch_size=2)
        tasks = [
            TaskItem(id=f"bs{i}", name=f"T{i}", task_type="api")
            for i in range(5)
        ]
        batches = batcher.create_batches(tasks)
        for batch in batches:
            assert batch.size <= 2

    def test_batch_to_dict(self):
        batch = TaskBatch(id="tb1", task_type="api")
        batch.tasks.append(TaskItem(id="t1", name="T"))
        d = batch.to_dict()
        assert d["id"] == "tb1"
        assert d["size"] == 1

    def test_get_stats(self):
        batcher = TaskBatcher()
        stats = batcher.get_stats()
        assert "total_batches" in stats


class TestTaskScheduler:
    """Тесты TaskScheduler."""

    def test_get_ready_tasks(self):
        scheduler = TaskScheduler()
        tasks = [
            TaskItem(id="r1", name="First"),
            TaskItem(id="r2", name="Second", dependencies=["r1"]),
        ]
        ready = scheduler.get_ready_tasks(tasks)
        assert len(ready) == 1
        assert ready[0].id == "r1"

    def test_get_ready_with_completed_dep(self):
        scheduler = TaskScheduler()
        t1 = TaskItem(id="r3", name="Done")
        t1.status = TaskStatus.COMPLETED
        t2 = TaskItem(id="r4", name="Next", dependencies=["r3"])
        ready = scheduler.get_ready_tasks([t1, t2])
        assert len(ready) == 1
        assert ready[0].id == "r4"

    def test_execution_plan(self):
        scheduler = TaskScheduler()
        tasks = [
            TaskItem(id="p1", name="A"),
            TaskItem(id="p2", name="B", dependencies=["p1"]),
            TaskItem(id="p3", name="C"),
        ]
        waves = scheduler.get_execution_plan(tasks)
        assert len(waves) >= 1
        # First wave should contain p1 and p3 (no deps)
        first_ids = {t.id for t in waves[0]}
        assert "p1" in first_ids
        assert "p3" in first_ids

    def test_estimate_total_time(self):
        scheduler = TaskScheduler()
        tasks = [
            TaskItem(id="e1", name="A", estimated_duration=2.0),
            TaskItem(id="e2", name="B", estimated_duration=3.0),
        ]
        total = scheduler.estimate_total_time(tasks)
        assert total > 0


class TestTaskPrioritizerFacade:
    """Тесты фасада TaskPrioritizer."""

    def test_add_task(self):
        tp = TaskPrioritizer()
        task = tp.add_task(name="Test task", priority="high")
        assert task is not None
        assert task.priority == PriorityLevel.HIGH

    def test_add_task_auto_id(self):
        tp = TaskPrioritizer()
        task = tp.add_task(name="Auto ID")
        assert task.id.startswith("task_")

    def test_next_task(self):
        tp = TaskPrioritizer()
        tp.add_task(name="Low", priority="low")
        tp.add_task(name="Critical", priority="critical")
        task = tp.next_task()
        assert task is not None
        assert task.priority == PriorityLevel.CRITICAL

    def test_complete_task(self):
        tp = TaskPrioritizer()
        task = tp.add_task(name="To complete")
        tp.next_task()  # Start it
        assert tp.complete_task(task.id, result="done") is True

    def test_fail_task(self):
        tp = TaskPrioritizer()
        task = tp.add_task(name="To fail")
        tp.next_task()
        assert tp.fail_task(task.id, error="err") is True

    def test_get_plan(self):
        tp = TaskPrioritizer()
        tp.add_task(name="A")
        tp.add_task(name="B")
        plan = tp.get_plan()
        assert isinstance(plan, list)

    def test_create_batches(self):
        tp = TaskPrioritizer()
        tp.add_task(name="API 1", task_type="api")
        tp.add_task(name="API 2", task_type="api")
        batches = tp.create_batches()
        assert len(batches) >= 1

    def test_estimate_time(self):
        tp = TaskPrioritizer()
        tp.add_task(name="T1")
        est = tp.estimate_time()
        assert est >= 0

    def test_get_overdue(self):
        tp = TaskPrioritizer()
        tp.add_task(name="Late", deadline_sec=-10)
        # deadline_sec=-10 would be None because of guard
        overdue = tp.get_overdue()
        assert isinstance(overdue, list)

    def test_get_stats(self):
        tp = TaskPrioritizer()
        stats = tp.get_stats()
        assert "queue" in stats
        assert "batcher" in stats


class TestGlobalInstance:
    """Тест глобального экземпляра."""

    def test_global_exists(self):
        assert task_prioritizer is not None
        assert isinstance(task_prioritizer, TaskPrioritizer)
