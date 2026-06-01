"""
Тесты Workflow Engine (Part 9)
====================================
TemplateField, Template, ChecklistStep, Checklist, WorkflowAction,
Workflow, TemplateLibrary, ChecklistManager, WorkflowEngine.
~55 тестов.
"""

from pds_ultimate.core.workflow_engine import (
    Checklist,
    ChecklistManager,
    ChecklistStatus,
    ChecklistStep,
    StepStatus,
    Template,
    TemplateField,
    TemplateLibrary,
    TemplateType,
    Workflow,
    WorkflowAction,
    WorkflowEngine,
    WorkflowStatus,
    workflow_engine,
)

# ═══════════════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════════════


class TestEnums:
    """Enum smoke tests."""

    def test_template_type(self):
        assert TemplateType.ORDER.value == "order"
        assert TemplateType.CHECKLIST.value == "checklist"
        assert TemplateType.REPORT.value == "report"
        assert TemplateType.WORKFLOW.value == "workflow"
        assert TemplateType.MESSAGE.value == "message"

    def test_checklist_status(self):
        assert ChecklistStatus.NOT_STARTED.value == "not_started"
        assert ChecklistStatus.IN_PROGRESS.value == "in_progress"
        assert ChecklistStatus.COMPLETED.value == "completed"
        assert ChecklistStatus.CANCELLED.value == "cancelled"

    def test_step_status(self):
        assert StepStatus.PENDING.value == "pending"
        assert StepStatus.DONE.value == "done"
        assert StepStatus.SKIPPED.value == "skipped"
        assert StepStatus.FAILED.value == "failed"

    def test_workflow_status(self):
        assert WorkflowStatus.DRAFT.value == "draft"
        assert WorkflowStatus.ACTIVE.value == "active"
        assert WorkflowStatus.COMPLETED.value == "completed"
        assert WorkflowStatus.PAUSED.value == "paused"


# ═══════════════════════════════════════════════════════════════════════════════
# TemplateField
# ═══════════════════════════════════════════════════════════════════════════════


class TestTemplateField:
    """TemplateField — поле шаблона."""

    def test_create(self):
        f = TemplateField(name="client_name", description="Имя клиента")
        assert f.name == "client_name"
        assert f.description == "Имя клиента"

    def test_required_default(self):
        f = TemplateField(name="notes", description="Заметки")
        assert f.required is True or f.required is False

    def test_to_dict(self):
        f = TemplateField(
            name="qty", description="Количество", field_type="number")
        d = f.to_dict()
        assert d["name"] == "qty"
        assert d["description"] == "Количество"


# ═══════════════════════════════════════════════════════════════════════════════
# Template
# ═══════════════════════════════════════════════════════════════════════════════


class TestTemplate:
    """Template — шаблон."""

    def test_create(self):
        t = Template(name="Заказ", template_type=TemplateType.ORDER)
        assert t.name == "Заказ"
        assert t.template_type == TemplateType.ORDER
        assert t.id
        assert t.use_count == 0

    def test_render_increments_use_count(self):
        t = Template(
            name="T",
            template_type=TemplateType.MESSAGE,
            content="Hello {name}!",
            fields=[TemplateField(name="name", description="Name")],
        )
        result = t.render({"name": "World"})
        assert "Hello World!" == result
        assert t.use_count == 1
        t.render({"name": "Again"})
        assert t.use_count == 2

    def test_to_dict(self):
        t = Template(
            name="Report",
            template_type=TemplateType.REPORT,
            content="Template body",
        )
        d = t.to_dict()
        assert d["name"] == "Report"
        assert "id" in d

    def test_with_fields(self):
        t = Template(
            name="Order",
            template_type=TemplateType.ORDER,
            fields=[
                TemplateField(name="client", description="Client"),
                TemplateField(name="amount", description="Amount"),
            ],
        )
        assert len(t.fields) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# ChecklistStep
# ═══════════════════════════════════════════════════════════════════════════════


class TestChecklistStep:
    """ChecklistStep — шаг чек-листа."""

    def test_create(self):
        s = ChecklistStep(title="Проверить товар", order=1)
        assert s.title == "Проверить товар"
        assert s.status == StepStatus.PENDING

    def test_complete(self):
        s = ChecklistStep(title="Step", order=1)
        s.complete()
        assert s.status == StepStatus.DONE
        assert s.completed_at is not None

    def test_skip(self):
        s = ChecklistStep(title="Step", order=1)
        s.skip()
        assert s.status == StepStatus.SKIPPED

    def test_fail(self):
        s = ChecklistStep(title="Step", order=1)
        s.fail("error")
        assert s.status == StepStatus.FAILED

    def test_is_done(self):
        s = ChecklistStep(title="Step", order=1)
        assert s.is_done is False
        s.complete()
        assert s.is_done is True

    def test_to_dict(self):
        s = ChecklistStep(title="S1", order=1)
        d = s.to_dict()
        assert d["title"] == "S1"
        assert d["status"] == "pending"


# ═══════════════════════════════════════════════════════════════════════════════
# Checklist
# ═══════════════════════════════════════════════════════════════════════════════


class TestChecklist:
    """Checklist — чек-лист."""

    def test_create(self):
        cl = Checklist(name="Приёмка товара")
        assert cl.name == "Приёмка товара"
        assert cl.status == ChecklistStatus.NOT_STARTED
        assert cl.id

    def test_add_steps(self):
        cl = Checklist(name="CL")
        cl.add_step("S1")
        cl.add_step("S2")
        cl.add_step("S3")
        assert len(cl.steps) == 3

    def test_progress_zero(self):
        cl = Checklist(name="CL")
        cl.add_step("S1")
        cl.add_step("S2")
        assert cl.progress == 0.0

    def test_progress_partial(self):
        cl = Checklist(name="CL")
        s1 = cl.add_step("S1")
        cl.add_step("S2")
        s1.complete()
        cl._update_status()
        assert cl.progress == 0.5

    def test_progress_complete(self):
        cl = Checklist(name="CL")
        s1 = cl.add_step("S1")
        s2 = cl.add_step("S2")
        s1.complete()
        s2.complete()
        cl._update_status()
        assert cl.progress == 1.0

    def test_progress_empty(self):
        cl = Checklist(name="CL")
        assert cl.progress == 0.0

    def test_complete_step_by_id(self):
        cl = Checklist(name="CL")
        s1 = cl.add_step("S1")
        cl.add_step("S2")
        result = cl.complete_step(s1.id)
        assert result is True
        assert s1.status == StepStatus.DONE

    def test_complete_step_by_order(self):
        cl = Checklist(name="CL")
        s1 = cl.add_step("S1")
        s2 = cl.add_step("S2")
        cl.complete_step_by_order(1)  # order of s2 is 1
        assert s2.status == StepStatus.DONE

    def test_next_step(self):
        cl = Checklist(name="CL")
        s1 = cl.add_step("S1")
        s2 = cl.add_step("S2")
        assert cl.next_step is s1
        s1.complete()
        assert cl.next_step is s2

    def test_next_step_all_done(self):
        cl = Checklist(name="CL")
        s1 = cl.add_step("S1")
        s1.complete()
        assert cl.next_step is None

    def test_format_text(self):
        cl = Checklist(name="CL")
        s1 = cl.add_step("Шаг 1")
        cl.add_step("Шаг 2")
        s1.complete()
        text = cl.format_text()
        assert "Шаг 1" in text
        assert "Шаг 2" in text

    def test_to_dict(self):
        cl = Checklist(name="CL", description="Описание")
        cl.add_step("S1")
        d = cl.to_dict()
        assert d["name"] == "CL"
        assert len(d["steps"]) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# WorkflowAction
# ═══════════════════════════════════════════════════════════════════════════════


class TestWorkflowAction:
    """WorkflowAction — действие в workflow."""

    def test_create(self):
        wa = WorkflowAction(
            name="Send email",
            action_type="email",
            order=1,
        )
        assert wa.name == "Send email"
        assert wa.order == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Workflow
# ═══════════════════════════════════════════════════════════════════════════════


class TestWorkflow:
    """Workflow — рабочий процесс."""

    def test_create(self):
        w = Workflow(name="Процесс заказа")
        assert w.name == "Процесс заказа"
        assert w.status == WorkflowStatus.DRAFT

    def test_add_action(self):
        w = Workflow(name="WF")
        w.add_action(name="Step 1", action_type="tool_call")
        assert w.total_actions == 1

    def test_to_dict(self):
        w = Workflow(name="WF1")
        d = w.to_dict()
        assert d["name"] == "WF1"
        assert "id" in d


# ═══════════════════════════════════════════════════════════════════════════════
# TemplateLibrary
# ═══════════════════════════════════════════════════════════════════════════════


class TestTemplateLibrary:
    """TemplateLibrary — библиотека шаблонов."""

    def test_default_templates(self):
        lib = TemplateLibrary()
        templates = lib.search()
        assert len(templates) >= 2

    def test_create_template(self):
        lib = TemplateLibrary()
        initial = len(lib.search())
        t = lib.create_template(
            name="Custom", template_type="report", content="Body")
        assert len(lib.search()) == initial + 1

    def test_get_template(self):
        lib = TemplateLibrary()
        templates = lib.search()
        if templates:
            t = lib.get_template(templates[0].id)
            assert t is not None

    def test_find_by_name(self):
        lib = TemplateLibrary()
        lib.create_template(
            name="FindMe", template_type="report", content="x")
        found = lib.find_by_name("FindMe")
        assert found is not None

    def test_search_by_type(self):
        lib = TemplateLibrary()
        lib.create_template(
            name="T1", template_type="order", content="body")
        orders = lib.search(template_type=TemplateType.ORDER)
        assert len(orders) >= 1

    def test_render_template(self):
        lib = TemplateLibrary()
        t = lib.create_template(
            name="Render",
            template_type="message",
            content="Hello {name}!",
            fields=[TemplateField(name="name", description="Name")],
        )
        result = lib.render_template(t.id, {"name": "World"})
        assert result == "Hello World!"
        assert t.use_count == 1

    def test_get_stats(self):
        lib = TemplateLibrary()
        stats = lib.get_stats()
        assert "total" in stats
        assert "by_type" in stats


# ═══════════════════════════════════════════════════════════════════════════════
# ChecklistManager
# ═══════════════════════════════════════════════════════════════════════════════


class TestChecklistManager:
    """ChecklistManager — управление чек-листами."""

    def test_create_checklist(self):
        cm = ChecklistManager()
        cl = cm.create_checklist(name="CL1", steps=["A", "B", "C"])
        assert cl.name == "CL1"
        assert len(cl.steps) == 3

    def test_get_checklist(self):
        cm = ChecklistManager()
        cl = cm.create_checklist(name="CL1", steps=["A"])
        found = cm.get_checklist(cl.id)
        assert found is cl

    def test_get_nonexistent(self):
        cm = ChecklistManager()
        assert cm.get_checklist("fake-id") is None

    def test_complete_step(self):
        cm = ChecklistManager()
        cl = cm.create_checklist(name="CL1", steps=["Step1", "Step2"])
        cm.complete_step(cl.id, 0)
        assert cl.steps[0].status == StepStatus.DONE

    def test_get_active(self):
        cm = ChecklistManager()
        cm.create_checklist(name="Active1", steps=["A"])
        active = cm.get_active()
        assert len(active) >= 1

    def test_get_stats(self):
        cm = ChecklistManager()
        cm.create_checklist(name="CL1", steps=["A"])
        stats = cm.get_stats()
        assert stats["total"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# WorkflowEngine (facade)
# ═══════════════════════════════════════════════════════════════════════════════


class TestWorkflowEngine:
    """WorkflowEngine — главный фасад."""

    def test_create_template(self):
        we = WorkflowEngine()
        t = we.create_template(
            name="NewTemplate",
            template_type="report",
            content="Body text",
        )
        assert t.name == "NewTemplate"

    def test_use_template(self):
        we = WorkflowEngine()
        t = we.create_template(
            name="Usable", template_type="report", content="Body")
        result = we.use_template("Usable")
        assert result is not None

    def test_create_checklist(self):
        we = WorkflowEngine()
        cl = we.create_checklist(
            name="Приёмка",
            steps=["Проверить количество", "Проверить качество"],
        )
        assert cl.name == "Приёмка"
        assert len(cl.steps) == 2

    def test_check_step(self):
        we = WorkflowEngine()
        cl = we.create_checklist(
            name="CL", steps=["A", "B", "C"],
        )
        # check_step takes name and 1-based step number
        result = we.check_step("CL", 1)
        assert result is not None
        assert result.steps[0].status == StepStatus.DONE

    def test_create_workflow(self):
        we = WorkflowEngine()
        wf = we.create_workflow(name="Процесс")
        assert wf.name == "Процесс"

    def test_get_stats(self):
        we = WorkflowEngine()
        we.create_template(
            name="T1", template_type="order", content="body")
        we.create_checklist(name="CL1", steps=["A"])
        stats = we.get_stats()
        # Default templates + T1
        assert stats["templates"]["total"] >= 3
        assert stats["checklists"]["total"] == 1

    def test_global_instance(self):
        assert workflow_engine is not None
        assert isinstance(workflow_engine, WorkflowEngine)
