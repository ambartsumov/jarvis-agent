"""
PDS-Ultimate Cognitive Engine Tests (Part 3)
=============================================
Тесты когнитивного движка.

Тестируем:
1. DAGNode — создание, статусы, retry
2. DAGPlan — граф, зависимости, параллельные узлы, cycles, progress
3. TaskManager — приоритеты, дедлайны, urgency scoring
4. Dynamic Roles — RoleManager, role switching, role prompts
5. MetacognitiveState — зацикливание, время, abort conditions
6. CognitiveEngine — интеграция всех компонент
7. ConfidenceAssessment — оценка уверенности
8. GoalIntegrityCheck — целостность цели
9. Edge Cases — пустые данные, границы, стресс
"""

from datetime import datetime, timedelta

import pytest

from pds_ultimate.core.cognitive_engine import (
    AgentRole,
    CognitiveEngine,
    ConfidenceAssessment,
    DAGNode,
    DAGPlan,
    GoalIntegrityCheck,
    ManagedTask,
    MetacognitiveState,
    NodeStatus,
    RoleManager,
    TaskManager,
    TaskPriority,
    cognitive_engine,
)

# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def plan():
    """Fresh DAG plan."""
    return DAGPlan("Test Goal")


@pytest.fixture
def task_mgr():
    """Fresh TaskManager."""
    return TaskManager()


@pytest.fixture
def role_mgr():
    """Fresh RoleManager."""
    return RoleManager()


@pytest.fixture
def engine():
    """Fresh CognitiveEngine."""
    return CognitiveEngine()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. DAG NODE
# ═══════════════════════════════════════════════════════════════════════════════

class TestDAGNode:
    """Тесты узла DAG."""

    def test_create_node(self):
        """Базовое создание."""
        node = DAGNode(id="step_1", description="Test step")
        assert node.id == "step_1"
        assert node.status == NodeStatus.PENDING
        assert node.depends_on == []
        assert node.retry_count == 0
        assert node.max_retries == 2

    def test_is_terminal(self):
        """Терминальные статусы."""
        node = DAGNode(id="n", description="n")
        assert node.is_terminal is False

        node.status = NodeStatus.COMPLETED
        assert node.is_terminal is True

        node.status = NodeStatus.FAILED
        assert node.is_terminal is True

        node.status = NodeStatus.SKIPPED
        assert node.is_terminal is True

        node.status = NodeStatus.RUNNING
        assert node.is_terminal is False

    def test_can_retry(self):
        """Логика retry."""
        node = DAGNode(id="n", description="n", max_retries=2)
        assert node.can_retry() is True  # 0 < 2

        node.retry_count = 1
        assert node.can_retry() is True  # 1 < 2

        node.retry_count = 2
        assert node.can_retry() is False  # 2 >= 2

    def test_duration(self):
        """Время выполнения."""
        node = DAGNode(id="n", description="n")
        assert node.duration_ms == 0

        node.started_at = 100.0
        node.completed_at = 100.5
        assert node.duration_ms == 500

    def test_node_statuses_enum(self):
        """Все статусы определены."""
        assert NodeStatus.PENDING == "pending"
        assert NodeStatus.READY == "ready"
        assert NodeStatus.RUNNING == "running"
        assert NodeStatus.COMPLETED == "completed"
        assert NodeStatus.FAILED == "failed"
        assert NodeStatus.SKIPPED == "skipped"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. DAG PLAN
# ═══════════════════════════════════════════════════════════════════════════════

class TestDAGPlan:
    """Тесты DAG плана."""

    def test_create_plan(self, plan):
        """Создание пустого плана."""
        assert plan.goal == "Test Goal"
        assert len(plan.nodes) == 0
        assert plan.is_complete is True  # Пустой → complete
        assert plan.progress == 1.0

    def test_add_nodes(self, plan):
        """Добавление узлов."""
        plan.add_node("s1", "Step 1")
        plan.add_node("s2", "Step 2")
        assert len(plan.nodes) == 2
        assert plan.is_complete is False

    def test_dependencies(self, plan):
        """Зависимости между узлами."""
        plan.add_node("s1", "Step 1")
        plan.add_node("s2", "Step 2", depends_on=["s1"])
        plan.add_node("s3", "Step 3", depends_on=["s1"])
        plan.add_node("s4", "Step 4", depends_on=["s2", "s3"])

        # Только s1 готов (нет зависимостей)
        ready = plan.get_ready_nodes()
        assert len(ready) == 1
        assert ready[0].id == "s1"

    def test_parallel_nodes(self, plan):
        """Параллельные (независимые) узлы."""
        plan.add_node("a", "Task A")
        plan.add_node("b", "Task B")
        plan.add_node("c", "Task C")

        ready = plan.get_ready_nodes()
        assert len(ready) == 3  # Все параллельны

    def test_priority_ordering(self, plan):
        """Приоритет определяет порядок."""
        plan.add_node("low", "Low prio", priority=1)
        plan.add_node("high", "High prio", priority=10)
        plan.add_node("mid", "Mid prio", priority=5)

        ready = plan.get_ready_nodes()
        assert ready[0].id == "high"
        assert ready[1].id == "mid"
        assert ready[2].id == "low"

    def test_complete_node(self, plan):
        """Завершение узла."""
        plan.add_node("s1", "Step 1")
        plan.add_node("s2", "Step 2", depends_on=["s1"])

        plan.complete_node("s1", "Done!")
        assert plan.nodes["s1"].status == NodeStatus.COMPLETED
        assert plan.nodes["s1"].result == "Done!"

        # Теперь s2 готов
        ready = plan.get_ready_nodes()
        assert len(ready) == 1
        assert ready[0].id == "s2"

    def test_fail_node_with_retry(self, plan):
        """Неудача с retry."""
        plan.add_node("s1", "Step 1", max_retries=2)

        can_retry = plan.fail_node("s1", "Error 1")
        assert can_retry is True
        assert plan.nodes["s1"].status == NodeStatus.PENDING
        assert plan.nodes["s1"].retry_count == 1

    def test_fail_node_exhausted(self, plan):
        """Неудача: исчерпаны retry."""
        plan.add_node("s1", "Step 1", max_retries=1)

        plan.fail_node("s1", "Error 1")  # retry 1
        can_retry = plan.fail_node("s1", "Error 2")  # retry exhausted
        assert can_retry is False
        assert plan.nodes["s1"].status == NodeStatus.FAILED

    def test_skip_dependents_on_failure(self, plan):
        """Зависимые узлы пропускаются при неудаче."""
        plan.add_node("s1", "Step 1", max_retries=0)
        plan.add_node("s2", "Step 2", depends_on=["s1"])
        plan.add_node("s3", "Step 3", depends_on=["s2"])

        plan.fail_node("s1", "Fatal error")
        assert plan.nodes["s2"].status == NodeStatus.SKIPPED
        assert plan.nodes["s3"].status == NodeStatus.SKIPPED

    def test_remove_node(self, plan):
        """Удаление узла и зависимостей."""
        plan.add_node("s1", "Step 1")
        plan.add_node("s2", "Step 2", depends_on=["s1"])

        plan.remove_node("s1")
        assert "s1" not in plan.nodes
        assert plan.nodes["s2"].depends_on == []

    def test_progress(self, plan):
        """Отслеживание прогресса."""
        plan.add_node("s1", "Step 1")
        plan.add_node("s2", "Step 2")
        plan.add_node("s3", "Step 3")
        plan.add_node("s4", "Step 4")

        assert plan.progress == 0.0

        plan.complete_node("s1", "ok")
        assert plan.progress == 0.25

        plan.complete_node("s2", "ok")
        assert plan.progress == 0.5

    def test_has_failures(self, plan):
        """Обнаружение ошибок."""
        plan.add_node("s1", "Step 1", max_retries=0)
        assert plan.has_failures is False

        plan.fail_node("s1", "err")
        assert plan.has_failures is True

    def test_no_cycle_valid(self, plan):
        """Валидный DAG — нет циклов."""
        plan.add_node("s1", "A")
        plan.add_node("s2", "B", depends_on=["s1"])
        plan.add_node("s3", "C", depends_on=["s2"])
        assert plan.has_cycle() is False

    def test_cycle_detection(self):
        """Обнаружение цикла."""
        plan = DAGPlan("cycle test")
        plan.add_node("a", "A", depends_on=["c"])
        plan.add_node("b", "B", depends_on=["a"])
        plan.add_node("c", "C", depends_on=["b"])
        assert plan.has_cycle() is True

    def test_get_summary(self, plan):
        """Текстовое описание плана."""
        plan.add_node("s1", "First step")
        plan.add_node("s2", "Second step", depends_on=["s1"])
        plan.complete_node("s1", "Done")

        summary = plan.get_summary()
        assert "Test Goal" in summary
        assert "First step" in summary
        assert "✅" in summary

    def test_to_dict(self, plan):
        """Сериализация."""
        plan.add_node("s1", "Step 1", priority=5)
        d = plan.to_dict()
        assert d["goal"] == "Test Goal"
        assert "s1" in d["nodes"]
        assert d["nodes"]["s1"]["priority"] == 5

    def test_is_complete(self, plan):
        """Plan completeness."""
        plan.add_node("s1", "Step 1")
        assert plan.is_complete is False

        plan.complete_node("s1", "done")
        assert plan.is_complete is True

    def test_fail_nonexistent_node(self, plan):
        """Fail несуществующего узла."""
        result = plan.fail_node("nonexistent", "err")
        assert result is False

    def test_topological_sort_linear(self, plan):
        """Топологическая сортировка — линейная цепочка."""
        plan.add_node("s1", "Step 1")
        plan.add_node("s2", "Step 2", depends_on=["s1"])
        plan.add_node("s3", "Step 3", depends_on=["s2"])

        order = plan.topological_sort()
        assert order == ["s1", "s2", "s3"]

    def test_topological_sort_parallel(self, plan):
        """Топологическая сортировка — параллельные узлы по приоритету."""
        plan.add_node("low", "Low prio", priority=1)
        plan.add_node("high", "High prio", priority=10)
        plan.add_node("mid", "Mid prio", priority=5)

        order = plan.topological_sort()
        assert order[0] == "high"
        assert order[1] == "mid"
        assert order[2] == "low"

    def test_topological_sort_diamond(self, plan):
        """Топологическая сортировка — diamond pattern."""
        plan.add_node("a", "A")
        plan.add_node("b", "B", depends_on=["a"])
        plan.add_node("c", "C", depends_on=["a"])
        plan.add_node("d", "D", depends_on=["b", "c"])

        order = plan.topological_sort()
        assert order[0] == "a"
        assert order[-1] == "d"
        # b and c must come before d
        assert order.index("b") < order.index("d")
        assert order.index("c") < order.index("d")

    def test_topological_sort_empty(self, plan):
        """Топологическая сортировка — пустой план."""
        assert plan.topological_sort() == []

    def test_get_ready_nodes_idempotent(self, plan):
        """get_ready_nodes() — идемпотентный вызов (не мутирует статус)."""
        plan.add_node("s1", "Step 1")
        plan.add_node("s2", "Step 2")

        ready1 = plan.get_ready_nodes()
        ready2 = plan.get_ready_nodes()
        assert len(ready1) == len(ready2)
        # Статус не изменился
        assert plan.nodes["s1"].status == NodeStatus.PENDING
        assert plan.nodes["s2"].status == NodeStatus.PENDING


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TASK MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class TestTaskManager:
    """Тесты менеджера задач."""

    def test_create_task(self, task_mgr):
        """Создание задачи."""
        task = task_mgr.create_task("Buy supplies")
        assert task.description == "Buy supplies"
        assert task.priority == TaskPriority.NORMAL
        assert task.status == "pending"
        assert task.id.startswith("task_")

    def test_create_with_priority(self, task_mgr):
        """Создание с приоритетом."""
        task = task_mgr.create_task("Urgent!", priority=TaskPriority.CRITICAL)
        assert task.priority == TaskPriority.CRITICAL

    def test_create_with_string_priority(self, task_mgr):
        """Создание со строковым приоритетом."""
        task = task_mgr.create_task("Task", priority="high")
        assert task.priority == TaskPriority.HIGH

    def test_invalid_priority_defaults_to_normal(self, task_mgr):
        """Невалидный приоритет → NORMAL."""
        task = task_mgr.create_task("Task", priority="invalid")
        assert task.priority == TaskPriority.NORMAL

    def test_create_with_deadline(self, task_mgr):
        """Создание с дедлайном."""
        dl = datetime.utcnow() + timedelta(hours=2)
        task = task_mgr.create_task("Task", deadline=dl)
        assert task.deadline == dl
        assert task.is_overdue is False

    def test_overdue_task(self, task_mgr):
        """Просроченная задача."""
        dl = datetime.utcnow() - timedelta(hours=1)
        task = task_mgr.create_task("Late task", deadline=dl)
        assert task.is_overdue is True

    def test_urgency_score_priority(self, task_mgr):
        """Urgency зависит от приоритета."""
        low = task_mgr.create_task("Low", priority=TaskPriority.LOW)
        high = task_mgr.create_task("High", priority=TaskPriority.CRITICAL)
        assert high.urgency_score > low.urgency_score

    def test_urgency_score_deadline_boost(self, task_mgr):
        """Дедлайн увеличивает urgency."""
        no_dl = task_mgr.create_task("No deadline")
        soon = task_mgr.create_task(
            "Due soon",
            deadline=datetime.utcnow() + timedelta(minutes=30),
        )
        assert soon.urgency_score > no_dl.urgency_score

    def test_complete_task(self, task_mgr):
        """Завершение задачи."""
        task = task_mgr.create_task("Task")
        task_mgr.complete_task(task.id, "Done!")
        assert task.status == "completed"
        assert task.result == "Done!"
        assert task.completed_at is not None

    def test_fail_task(self, task_mgr):
        """Провал задачи."""
        task = task_mgr.create_task("Task")
        task_mgr.fail_task(task.id, "Error!")
        assert task.status == "failed"
        assert task.error == "Error!"

    def test_pause_resume(self, task_mgr):
        """Пауза и возобновление."""
        task = task_mgr.create_task("Task")
        task.status = "active"

        task_mgr.pause_task(task.id)
        assert task.status == "paused"

        task_mgr.resume_task(task.id)
        assert task.status == "pending"

    def test_get_next_task(self, task_mgr):
        """Получить следующую задачу по urgency."""
        task_mgr.create_task("Low", priority=TaskPriority.LOW)
        task_mgr.create_task("Critical", priority=TaskPriority.CRITICAL)
        task_mgr.create_task("Normal", priority=TaskPriority.NORMAL)

        next_task = task_mgr.get_next_task()
        assert next_task is not None
        assert next_task.priority == TaskPriority.CRITICAL

    def test_get_next_task_empty(self, task_mgr):
        """Нет задач → None."""
        assert task_mgr.get_next_task() is None

    def test_get_active_tasks(self, task_mgr):
        """Активные задачи."""
        task_mgr.create_task("T1", chat_id=100)
        task_mgr.create_task("T2", chat_id=200)
        task_mgr.create_task("T3", chat_id=100)

        all_active = task_mgr.get_active_tasks()
        assert len(all_active) == 3

        chat_100 = task_mgr.get_active_tasks(chat_id=100)
        assert len(chat_100) == 2

    def test_get_overdue_tasks(self, task_mgr):
        """Просроченные задачи."""
        task_mgr.create_task("Normal")
        task_mgr.create_task(
            "Overdue", deadline=datetime.utcnow() - timedelta(hours=1))

        overdue = task_mgr.get_overdue_tasks()
        assert len(overdue) == 1

    def test_get_completed_tasks(self, task_mgr):
        """Завершённые задачи."""
        t1 = task_mgr.create_task("T1")
        t2 = task_mgr.create_task("T2")
        task_mgr.complete_task(t1.id, "ok1")
        task_mgr.complete_task(t2.id, "ok2")

        completed = task_mgr.get_completed_tasks()
        assert len(completed) == 2

    def test_stats(self, task_mgr):
        """Статистика."""
        task_mgr.create_task("T1")
        t2 = task_mgr.create_task("T2")
        task_mgr.complete_task(t2.id, "ok")

        stats = task_mgr.stats
        assert stats["total"] == 2
        assert stats["by_status"]["pending"] == 1
        assert stats["by_status"]["completed"] == 1

    def test_get_summary(self, task_mgr):
        """Текстовое описание."""
        task_mgr.create_task("Task 1", priority=TaskPriority.HIGH)
        summary = task_mgr.get_summary()
        assert "ЗАДАЧИ" in summary
        assert "Task 1" in summary

    def test_get_summary_empty(self, task_mgr):
        """Пустой менеджер."""
        summary = task_mgr.get_summary()
        assert "Нет активных задач" in summary

    def test_priority_weights(self):
        """Веса приоритетов."""
        assert TaskPriority.CRITICAL.weight > TaskPriority.HIGH.weight
        assert TaskPriority.HIGH.weight > TaskPriority.NORMAL.weight
        assert TaskPriority.NORMAL.weight > TaskPriority.LOW.weight
        assert TaskPriority.LOW.weight > TaskPriority.BACKGROUND.weight

    def test_completed_not_overdue(self, task_mgr):
        """Завершённая задача не считается просроченной."""
        t = task_mgr.create_task(
            "Done", deadline=datetime.utcnow() - timedelta(hours=1))
        task_mgr.complete_task(t.id, "ok")
        assert t.is_overdue is False


# ═══════════════════════════════════════════════════════════════════════════════
# 4. DYNAMIC ROLES
# ═══════════════════════════════════════════════════════════════════════════════

class TestRoleManager:
    """Тесты менеджера ролей."""

    def test_default_role(self, role_mgr):
        """По умолчанию — Executor."""
        assert role_mgr.active_role == AgentRole.EXECUTOR

    def test_switch_role(self, role_mgr):
        """Переключение роли."""
        prompt = role_mgr.switch_role(AgentRole.CRITIC)
        assert role_mgr.active_role == AgentRole.CRITIC
        assert "Critic" in prompt
        assert len(role_mgr.history) == 1

    def test_switch_role_string(self, role_mgr):
        """Переключение строковым значением."""
        prompt = role_mgr.switch_role("strategist")
        assert role_mgr.active_role == AgentRole.STRATEGIST
        assert "Strategist" in prompt

    def test_switch_invalid_role(self, role_mgr):
        """Невалидная роль — остаётся текущая."""
        role_mgr.switch_role("nonexistent")
        assert role_mgr.active_role == AgentRole.EXECUTOR

    def test_get_role_prompt(self, role_mgr):
        """Получение prompt для роли."""
        prompt = role_mgr.get_role_prompt(AgentRole.SUMMARIZER)
        assert "Summarizer" in prompt

    def test_suggest_role(self, role_mgr):
        """Автоматическое определение роли по задаче."""
        assert role_mgr.suggest_role("analyze data") == AgentRole.ANALYST
        assert role_mgr.suggest_role("plan the project") == AgentRole.PLANNER
        assert role_mgr.suggest_role("search for info") == AgentRole.RESEARCHER
        assert role_mgr.suggest_role("verify facts") == AgentRole.VERIFIER
        assert role_mgr.suggest_role("summarize text") == AgentRole.SUMMARIZER
        assert role_mgr.suggest_role("execute action") == AgentRole.EXECUTOR
        assert role_mgr.suggest_role("critique answer") == AgentRole.CRITIC
        assert role_mgr.suggest_role("decide strategy") == AgentRole.STRATEGIST

    def test_suggest_role_unknown(self, role_mgr):
        """Неизвестная задача → Executor."""
        assert role_mgr.suggest_role("blahblah") == AgentRole.EXECUTOR

    def test_role_history(self, role_mgr):
        """История переключений."""
        role_mgr.switch_role(AgentRole.CRITIC)
        role_mgr.switch_role(AgentRole.PLANNER)
        role_mgr.switch_role(AgentRole.EXECUTOR)

        assert len(role_mgr.history) == 3
        assert role_mgr.history[0]["to"] == "critic"
        assert role_mgr.history[2]["to"] == "executor"

    def test_all_roles_have_prompts(self):
        """Все роли имеют prompts."""
        from pds_ultimate.core.cognitive_engine import ROLE_PROMPTS
        for role in AgentRole:
            has_prompt = (role in ROLE_PROMPTS or role.value in ROLE_PROMPTS)
            assert has_prompt, f"Role {role} has no prompt"

    def test_all_roles_enum_values(self):
        """Все значения AgentRole — строки."""
        for role in AgentRole:
            assert isinstance(role.value, str)

    def test_per_chat_role_isolation(self, role_mgr):
        """Per-chat роли изолированы."""
        role_mgr.set_chat_role(100, AgentRole.CRITIC)
        role_mgr.set_chat_role(200, AgentRole.PLANNER)

        assert role_mgr.get_chat_role(100) == AgentRole.CRITIC
        assert role_mgr.get_chat_role(200) == AgentRole.PLANNER
        # Неизвестный chat → global active_role
        assert role_mgr.get_chat_role(999) == role_mgr.active_role

    def test_per_chat_role_string(self, role_mgr):
        """Per-chat роль по строке."""
        prompt = role_mgr.set_chat_role(100, "analyst")
        assert role_mgr.get_chat_role(100) == AgentRole.ANALYST
        assert "Analyst" in prompt

    def test_per_chat_role_invalid(self, role_mgr):
        """Невалидная per-chat роль — остаётся текущая."""
        role_mgr.set_chat_role(100, AgentRole.CRITIC)
        # Попытка установить невалидную
        role_mgr.set_chat_role(100, "nonexistent")
        # При невалидной строке get_chat_role возвращает текущий active_role
        # Но конкретно в нашей реализации — не обновляет per-chat, возвращает prompt
        assert role_mgr.get_chat_role(100) == AgentRole.CRITIC


# ═══════════════════════════════════════════════════════════════════════════════
# 5. METACOGNITIVE STATE
# ═══════════════════════════════════════════════════════════════════════════════

class TestMetacognitiveState:
    """Тесты метакогнитивного состояния."""

    def test_initial_state(self):
        """Начальное состояние."""
        mc = MetacognitiveState()
        assert mc.iterations_used == 0
        assert mc.thinking_time_seconds == 0.0
        assert mc.avg_quality == 0.0
        assert mc.avg_confidence == 0.0
        assert mc.is_stuck is False
        assert mc.is_taking_too_long is False
        assert mc.should_abort is False

    def test_is_stuck_detection(self):
        """Обнаружение зацикливания."""
        mc = MetacognitiveState()
        mc.repeated_actions = ["search", "search", "search"]
        assert mc.is_stuck is True

    def test_not_stuck_different_actions(self):
        """Разные действия — не зацикливание."""
        mc = MetacognitiveState()
        mc.repeated_actions = ["search", "analyze", "search"]
        assert mc.is_stuck is False

    def test_is_taking_too_long(self):
        """Слишком долго."""
        mc = MetacognitiveState()
        mc.thinking_time_seconds = 150  # > 120
        assert mc.is_taking_too_long is True

    def test_should_abort_stuck(self):
        """Abort при зацикливании."""
        mc = MetacognitiveState()
        mc.repeated_actions = ["x", "x", "x"]
        assert mc.should_abort is True

    def test_should_abort_too_many_iterations(self):
        """Abort при превышении итераций."""
        mc = MetacognitiveState()
        mc.iterations_used = 20
        assert mc.should_abort is True

    def test_should_abort_timeout(self):
        """Abort при таймауте."""
        mc = MetacognitiveState()
        mc.thinking_time_seconds = 400
        assert mc.should_abort is True

    def test_avg_quality(self):
        """Средняя оценка качества."""
        mc = MetacognitiveState()
        mc.quality_scores = [0.8, 0.6, 0.9]
        assert abs(mc.avg_quality - 0.7667) < 0.01

    def test_avg_confidence(self):
        """Средняя уверенность."""
        mc = MetacognitiveState()
        mc.confidence_history = [0.9, 0.7, 0.8]
        assert abs(mc.avg_confidence - 0.8) < 0.01

    def test_declining_confidence(self):
        """Обнаружение снижающейся уверенности."""
        mc = MetacognitiveState()
        mc.confidence_history = [0.9, 0.7, 0.5]
        assert mc.is_declining is True

    def test_not_declining_confidence(self):
        """Уверенность не снижается."""
        mc = MetacognitiveState()
        mc.confidence_history = [0.5, 0.7, 0.9]
        assert mc.is_declining is False

    def test_declining_too_few_points(self):
        """Слишком мало данных для определения decline."""
        mc = MetacognitiveState()
        mc.confidence_history = [0.9, 0.7]
        assert mc.is_declining is False

    def test_low_confidence_streak(self):
        """Подряд идущие низкие оценки уверенности."""
        mc = MetacognitiveState()
        mc.confidence_history = [0.8, 0.6, 0.3, 0.2, 0.1]
        assert mc.low_confidence_streak == 3  # 0.3, 0.2, 0.1

    def test_low_confidence_streak_none(self):
        """Нет низких оценок уверенности подряд."""
        mc = MetacognitiveState()
        mc.confidence_history = [0.8, 0.7, 0.9]
        assert mc.low_confidence_streak == 0

    def test_should_abort_low_confidence_streak(self):
        """Abort при 4+ подряд низких оценках."""
        mc = MetacognitiveState()
        mc.confidence_history = [0.8, 0.3, 0.2, 0.1, 0.05]
        assert mc.low_confidence_streak == 4
        assert mc.should_abort is True


# ═══════════════════════════════════════════════════════════════════════════════
# 6. CONFIDENCE ASSESSMENT
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfidenceAssessment:
    """Тесты оценки уверенности."""

    def test_high_confidence(self):
        """Высокая уверенность."""
        ca = ConfidenceAssessment(
            score=0.9, reasoning="Good", gaps=[], should_search_more=False,
            suggested_queries=[])
        assert ca.is_high is True
        assert ca.is_medium is False
        assert ca.is_low is False

    def test_medium_confidence(self):
        """Средняя уверенность."""
        ca = ConfidenceAssessment(
            score=0.6, reasoning="OK", gaps=["missing data"],
            should_search_more=True, suggested_queries=["more info"])
        assert ca.is_medium is True
        assert ca.is_high is False
        assert ca.is_low is False

    def test_low_confidence(self):
        """Низкая уверенность."""
        ca = ConfidenceAssessment(
            score=0.3, reasoning="Uncertain", gaps=["a", "b"],
            should_search_more=True, suggested_queries=["q1", "q2"])
        assert ca.is_low is True
        assert ca.is_high is False

    def test_boundary_values(self):
        """Граничные значения."""
        assert ConfidenceAssessment(
            score=0.5, reasoning="", gaps=[],
            should_search_more=False, suggested_queries=[]).is_medium is True
        assert ConfidenceAssessment(
            score=0.75, reasoning="", gaps=[],
            should_search_more=False, suggested_queries=[]).is_high is True
        assert ConfidenceAssessment(
            score=0.49, reasoning="", gaps=[],
            should_search_more=False, suggested_queries=[]).is_low is True


# ═══════════════════════════════════════════════════════════════════════════════
# 7. GOAL INTEGRITY CHECK
# ═══════════════════════════════════════════════════════════════════════════════

class TestGoalIntegrityCheck:
    """Тесты целостности цели."""

    def test_aligned(self):
        """Цель выровнена."""
        check = GoalIntegrityCheck(
            aligned=True,
            original_goal="Buy supplies",
            current_focus="Searching suppliers",
            drift_reason=None,
            recommendation="Continue",
        )
        assert check.aligned is True
        assert check.drift_reason is None

    def test_drifted(self):
        """Цель отклонилась."""
        check = GoalIntegrityCheck(
            aligned=False,
            original_goal="Buy supplies",
            current_focus="Reading news",
            drift_reason="Got distracted by news",
            recommendation="Return to supplier search",
        )
        assert check.aligned is False
        assert check.drift_reason is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 8. COGNITIVE ENGINE — Integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestCognitiveEngine:
    """Тесты когнитивного движка."""

    def test_create_engine(self, engine):
        """Создание движка."""
        assert engine.task_manager is not None
        assert engine.role_manager is not None

    def test_metacog_per_chat(self, engine):
        """Метакогниция per-chat."""
        mc1 = engine.get_metacog(100)
        mc2 = engine.get_metacog(200)
        assert mc1 is not mc2

        mc1_again = engine.get_metacog(100)
        assert mc1 is mc1_again

    def test_reset_metacog(self, engine):
        """Сброс метакогниции."""
        mc = engine.get_metacog(100)
        mc.iterations_used = 10
        engine.reset_metacog(100)
        mc_new = engine.get_metacog(100)
        assert mc_new.iterations_used == 0

    def test_record_action(self, engine):
        """Запись действия."""
        engine.record_action(100, "search", duration_s=0.5)
        mc = engine.get_metacog(100)
        assert mc.iterations_used == 1
        assert mc.thinking_time_seconds == 0.5
        assert mc.repeated_actions == ["search"]

    def test_record_confidence(self, engine):
        """Запись уверенности."""
        engine.record_confidence(100, 0.8)
        engine.record_confidence(100, 0.6)
        mc = engine.get_metacog(100)
        assert len(mc.confidence_history) == 2
        assert mc.avg_confidence == 0.7

    def test_record_quality(self, engine):
        """Запись качества."""
        engine.record_quality(100, 0.9)
        mc = engine.get_metacog(100)
        assert mc.avg_quality == 0.9

    def test_confidence_clamped(self, engine):
        """Confidence clamped to [0, 1]."""
        engine.record_confidence(100, 5.0)
        engine.record_confidence(100, -1.0)
        mc = engine.get_metacog(100)
        assert mc.confidence_history == [1.0, 0.0]

    def test_create_plan(self, engine):
        """Создание плана."""
        plan = engine.create_plan(100, "Test goal")
        assert plan.goal == "Test goal"
        assert engine.get_plan(100) is plan

    def test_clear_plan(self, engine):
        """Очистка плана."""
        engine.create_plan(100, "goal")
        engine.clear_plan(100)
        assert engine.get_plan(100) is None

    def test_get_cognitive_context_empty(self, engine):
        """Пустой контекст."""
        ctx = engine.get_cognitive_context(999)
        assert ctx == ""

    def test_get_cognitive_context_with_plan(self, engine):
        """Контекст с планом."""
        plan = engine.create_plan(100, "Important goal")
        plan.add_node("s1", "Step 1")

        ctx = engine.get_cognitive_context(100)
        assert "Important goal" in ctx

    def test_get_cognitive_context_with_tasks(self, engine):
        """Контекст с задачами."""
        engine.task_manager.create_task(
            "Task 1", chat_id=100, priority=TaskPriority.HIGH)

        ctx = engine.get_cognitive_context(100)
        assert "Task 1" in ctx

    def test_get_cognitive_context_with_metacog(self, engine):
        """Контекст с метакогницией."""
        engine.record_action(100, "search", 0.5)
        engine.record_confidence(100, 0.8)

        ctx = engine.get_cognitive_context(100)
        assert "МЕТАКОГНИЦИЯ" in ctx

    def test_get_cognitive_context_stuck_warning(self, engine):
        """Предупреждение о зацикливании."""
        engine.record_action(100, "search")
        engine.record_action(100, "search")
        engine.record_action(100, "search")

        ctx = engine.get_cognitive_context(100)
        assert "ЗАЦИКЛИВАНИЕ" in ctx

    def test_get_stats(self, engine):
        """Статистика."""
        engine.create_plan(100, "goal")
        engine.task_manager.create_task("T1")

        stats = engine.get_stats()
        assert stats["active_plans"] == 1
        assert stats["tasks"]["total"] == 1
        assert stats["active_role"] == "executor"

    def test_global_instance(self):
        """Глобальный экземпляр."""
        assert cognitive_engine is not None
        assert isinstance(cognitive_engine, CognitiveEngine)

    def test_action_history_capped(self, engine):
        """История действий ограничена."""
        for i in range(100):
            engine.record_action(100, f"action_{i}")
        mc = engine.get_metacog(100)
        assert len(mc.repeated_actions) <= 50


# ═══════════════════════════════════════════════════════════════════════════════
# 9. EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Граничные случаи."""

    def test_empty_dag_plan(self):
        """Пустой DAG план."""
        plan = DAGPlan("empty")
        assert plan.is_complete is True
        assert plan.progress == 1.0
        assert plan.get_ready_nodes() == []
        assert plan.has_failures is False

    def test_single_node_plan(self):
        """План с 1 узлом."""
        plan = DAGPlan("single")
        plan.add_node("only", "Only step")
        assert plan.progress == 0.0
        assert len(plan.get_ready_nodes()) == 1

        plan.complete_node("only", "done")
        assert plan.is_complete is True
        assert plan.progress == 1.0

    def test_dag_with_many_nodes(self):
        """План с множеством узлов."""
        plan = DAGPlan("big")
        for i in range(50):
            deps = [f"step_{i-1}"] if i > 0 else []
            plan.add_node(f"step_{i}", f"Step {i}", depends_on=deps)

        # Только первый готов
        ready = plan.get_ready_nodes()
        assert len(ready) == 1
        assert ready[0].id == "step_0"

    def test_task_manager_many_tasks(self, task_mgr):
        """Множество задач."""
        for i in range(100):
            task_mgr.create_task(f"Task {i}")
        assert task_mgr.stats["total"] == 100

    def test_role_switch_rapid(self, role_mgr):
        """Быстрое переключение ролей."""
        for role in AgentRole:
            role_mgr.switch_role(role)
        assert len(role_mgr.history) == len(list(AgentRole))

    def test_dag_diamond_dependency(self):
        """Diamond dependency pattern: A → B, A → C, B+C → D."""
        plan = DAGPlan("diamond")
        plan.add_node("a", "Start")
        plan.add_node("b", "Left branch", depends_on=["a"])
        plan.add_node("c", "Right branch", depends_on=["a"])
        plan.add_node("d", "Merge", depends_on=["b", "c"])

        # Only A ready
        ready = plan.get_ready_nodes()
        assert len(ready) == 1
        assert ready[0].id == "a"

        # Complete A → B and C ready
        plan.complete_node("a", "ok")
        ready = plan.get_ready_nodes()
        assert len(ready) == 2
        ids = {n.id for n in ready}
        assert ids == {"b", "c"}

        # Complete B → C still ready, D not (C not completed)
        plan.complete_node("b", "ok")
        ready = plan.get_ready_nodes()
        # get_ready_nodes() is idempotent — C is still PENDING
        assert len(ready) == 1
        assert ready[0].id == "c"

        # Complete C → D ready
        plan.complete_node("c", "ok")
        ready = plan.get_ready_nodes()
        assert len(ready) == 1
        assert ready[0].id == "d"

        # Complete D → plan done
        plan.complete_node("d", "ok")
        assert plan.is_complete is True

    def test_managed_task_no_deadline_not_overdue(self):
        """Задача без дедлайна не может быть просрочена."""
        task = ManagedTask(id="t1", description="no deadline")
        assert task.is_overdue is False

    def test_summary_with_deadline_formats(self, task_mgr):
        """Summary форматирует разные дедлайны."""
        task_mgr.create_task(
            "Minutes", deadline=datetime.utcnow() + timedelta(minutes=30))
        task_mgr.create_task(
            "Hours", deadline=datetime.utcnow() + timedelta(hours=5))
        task_mgr.create_task(
            "Days", deadline=datetime.utcnow() + timedelta(days=3))
        task_mgr.create_task(
            "Overdue", deadline=datetime.utcnow() - timedelta(hours=1))

        summary = task_mgr.get_summary()
        assert "ЗАДАЧИ" in summary
        assert "⏰" in summary
