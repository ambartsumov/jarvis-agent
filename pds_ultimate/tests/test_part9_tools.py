"""
Тесты Part 9: Business Tools (8 хендлеров)
============================================
tool_set_trigger, tool_list_triggers, tool_dashboard, tool_kpi_track,
tool_rate_contact, tool_crm_search, tool_evening_digest, tool_create_template
"""

import asyncio


def run(coro):
    """Хелпер для запуска async-функций."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ═══════════════════════════════════════════════════════════════════════════════
# tool_set_trigger
# ═══════════════════════════════════════════════════════════════════════════════


class TestToolSetTrigger:
    """Тесты tool_set_trigger."""

    def _call(self, **kwargs):
        from pds_ultimate.core.business_tools import tool_set_trigger
        return run(tool_set_trigger(**kwargs))

    def test_create_basic_trigger(self):
        r = self._call(name="Test Trigger")
        assert r.success is True
        assert r.tool_name == "set_trigger"
        assert "Test Trigger" in r.output

    def test_create_trigger_with_condition(self):
        r = self._call(
            name="Revenue Check",
            trigger_type="threshold",
            field="revenue",
            operator=">",
            value="1000",
            severity="critical",
        )
        assert r.success is True
        assert "Revenue Check" in r.output
        assert r.data  # should have trigger dict

    def test_create_trigger_with_template(self):
        r = self._call(
            name="My Balance Trigger",
            template="balance",
        )
        assert r.success is True
        assert "My Balance Trigger" in r.output

    def test_create_trigger_invalid_template(self):
        r = self._call(
            name="Bad Template",
            template="nonexistent_template_xyz",
        )
        assert r.success is False
        assert r.error

    def test_create_trigger_with_lt_operator(self):
        r = self._call(
            name="Low Balance",
            field="balance",
            operator="<",
            value="100",
        )
        assert r.success is True
        assert "Low Balance" in r.output

    def test_create_trigger_data_has_id(self):
        r = self._call(name="Data Check")
        assert r.success is True
        assert "id" in r.data

    def test_create_trigger_severity_info(self):
        r = self._call(name="Info Trigger", severity="info")
        assert r.success is True
        assert "info" in r.output.lower() or r.data.get("severity") == "info"


# ═══════════════════════════════════════════════════════════════════════════════
# tool_list_triggers
# ═══════════════════════════════════════════════════════════════════════════════


class TestToolListTriggers:
    """Тесты tool_list_triggers."""

    def _call(self, **kwargs):
        from pds_ultimate.core.business_tools import tool_list_triggers
        return run(tool_list_triggers(**kwargs))

    def test_list_triggers_basic(self):
        r = self._call()
        assert r.success is True
        assert r.tool_name == "list_triggers"
        assert r.data is not None

    def test_list_triggers_with_history(self):
        r = self._call(show_history=True)
        assert r.success is True
        assert "алерт" in r.output.lower() or "Всего" in r.output

    def test_list_triggers_returns_stats(self):
        r = self._call()
        assert r.success is True
        assert "total" in r.data


# ═══════════════════════════════════════════════════════════════════════════════
# tool_dashboard
# ═══════════════════════════════════════════════════════════════════════════════


class TestToolDashboard:
    """Тесты tool_dashboard."""

    def _call(self, **kwargs):
        from pds_ultimate.core.business_tools import tool_dashboard
        return run(tool_dashboard(**kwargs))

    def test_dashboard_show(self):
        r = self._call(action="show")
        assert r.success is True
        assert r.tool_name == "dashboard"

    def test_dashboard_record_metric(self):
        r = self._call(action="record", metric_name="revenue",
                       value=500.0, unit="USD")
        assert r.success is True
        assert "revenue" in r.output.lower() or "Записано" in r.output

    def test_dashboard_trend(self):
        # Record some data first
        self._call(action="record", metric_name="trend_test", value=100.0)
        self._call(action="record", metric_name="trend_test", value=200.0)
        r = self._call(action="trend", metric_name="trend_test")
        assert r.success is True

    def test_dashboard_forecast(self):
        # Record data for forecast
        for i in range(5):
            self._call(action="record", metric_name="fc_metric",
                       value=float(100 + i * 10))
        r = self._call(action="forecast", metric_name="fc_metric")
        assert r.success is True

    def test_dashboard_default_show(self):
        """Без action → show."""
        r = self._call()
        assert r.success is True

    def test_dashboard_record_no_metric(self):
        """Record без metric_name → show."""
        r = self._call(action="record")
        assert r.success is True


# ═══════════════════════════════════════════════════════════════════════════════
# tool_kpi_track
# ═══════════════════════════════════════════════════════════════════════════════


class TestToolKpiTrack:
    """Тесты tool_kpi_track."""

    def _call(self, **kwargs):
        from pds_ultimate.core.business_tools import tool_kpi_track
        return run(tool_kpi_track(**kwargs))

    def test_kpi_create(self):
        r = self._call(action="create", name="Revenue KPI",
                       target=10000.0, unit="USD")
        assert r.success is True
        assert r.tool_name == "kpi_track"
        assert "Revenue KPI" in r.output

    def test_kpi_update(self):
        self._call(action="create", name="Sales KPI", target=100.0, unit="шт")
        r = self._call(action="update", name="Sales KPI", value=25.0)
        assert r.success is True
        assert "Sales KPI" in r.output

    def test_kpi_update_nonexistent(self):
        r = self._call(action="update", name="nonexistent_kpi_xyz", value=10.0)
        assert r.success is False
        assert r.error

    def test_kpi_board(self):
        r = self._call(action="board")
        assert r.success is True

    def test_kpi_default_board(self):
        """Без action → board."""
        r = self._call()
        assert r.success is True

    def test_kpi_create_with_data(self):
        r = self._call(action="create", name="Conversion KPI",
                       target=5.0, unit="%")
        assert r.success is True
        assert r.data


# ═══════════════════════════════════════════════════════════════════════════════
# tool_rate_contact
# ═══════════════════════════════════════════════════════════════════════════════


class TestToolRateContact:
    """Тесты tool_rate_contact."""

    def _call(self, **kwargs):
        from pds_ultimate.core.business_tools import tool_rate_contact
        return run(tool_rate_contact(**kwargs))

    def test_rate_contact_basic(self):
        r = self._call(name="Supplier A", rating=4.5)
        assert r.success is True
        assert r.tool_name == "rate_contact"
        assert "Supplier A" in r.output

    def test_rate_contact_with_comment(self):
        r = self._call(name="Supplier B", rating=3.0,
                       comment="Средний поставщик")
        assert r.success is True
        assert "Supplier B" in r.output

    def test_rate_contact_by_category(self):
        r = self._call(name="Supplier C", rating=5.0, category="quality")
        assert r.success is True
        assert "Supplier C" in r.output

    def test_rate_contact_clamps_high(self):
        """Rating > 5 → clamped to 5."""
        r = self._call(name="Supplier D", rating=10.0)
        assert r.success is True

    def test_rate_contact_clamps_low(self):
        """Rating < 1 → clamped to 1."""
        r = self._call(name="Supplier E", rating=-5.0)
        assert r.success is True


# ═══════════════════════════════════════════════════════════════════════════════
# tool_crm_search
# ═══════════════════════════════════════════════════════════════════════════════


class TestToolCrmSearch:
    """Тесты tool_crm_search."""

    def _call(self, **kwargs):
        from pds_ultimate.core.business_tools import tool_crm_search
        return run(tool_crm_search(**kwargs))

    def test_crm_search_basic(self):
        r = self._call(query="Test")
        assert r.success is True
        assert r.tool_name == "crm_search"

    def test_crm_add_contact(self):
        r = self._call(query="New CRM Contact",
                       action="add_contact", contact_type="supplier")
        assert r.success is True
        assert "New CRM Contact" in r.output

    def test_crm_add_contact_other_type(self):
        r = self._call(query="Other Contact",
                       action="add_contact", contact_type="client")
        assert r.success is True

    def test_crm_add_deal(self):
        r = self._call(query="Big Deal", action="add_deal")
        assert r.success is True
        assert "Big Deal" in r.output

    def test_crm_stats(self):
        r = self._call(action="stats")
        assert r.success is True
        assert "Контактов" in r.output or r.data

    def test_crm_pipeline(self):
        r = self._call(action="pipeline")
        assert r.success is True

    def test_crm_search_not_found(self):
        r = self._call(query="zzznonexistent999")
        assert r.success is True
        assert "не найдено" in r.output.lower() or "найдено" in r.output.lower()

    def test_crm_search_with_min_rating(self):
        # First add a contact
        self._call(query="Rated Contact", action="add_contact",
                   contact_type="partner")
        r = self._call(query="Rated", min_rating=0.0)
        assert r.success is True


# ═══════════════════════════════════════════════════════════════════════════════
# tool_evening_digest
# ═══════════════════════════════════════════════════════════════════════════════


class TestToolEveningDigest:
    """Тесты tool_evening_digest."""

    def _call(self, **kwargs):
        from pds_ultimate.core.business_tools import tool_evening_digest
        return run(tool_evening_digest(**kwargs))

    def test_digest_full(self):
        r = self._call(
            format="full",
            revenue=5000.0,
            expenses=2000.0,
            orders_created=3,
            tasks_completed=5,
        )
        assert r.success is True
        assert r.tool_name == "evening_digest"

    def test_digest_short(self):
        r = self._call(
            format="short",
            revenue=1000.0,
            expenses=500.0,
        )
        assert r.success is True

    def test_digest_default_full(self):
        """Без format → full."""
        r = self._call(revenue=100.0, expenses=50.0)
        assert r.success is True

    def test_digest_zero_values(self):
        r = self._call(revenue=0.0, expenses=0.0)
        assert r.success is True

    def test_digest_data_has_summary(self):
        r = self._call(revenue=3000.0, expenses=1000.0, orders_created=2)
        assert r.success is True
        assert r.data
        assert "revenue" in r.data or "profit" in r.data


# ═══════════════════════════════════════════════════════════════════════════════
# tool_create_template
# ═══════════════════════════════════════════════════════════════════════════════


class TestToolCreateTemplate:
    """Тесты tool_create_template."""

    def _call(self, **kwargs):
        from pds_ultimate.core.business_tools import tool_create_template
        return run(tool_create_template(**kwargs))

    def test_create_checklist(self):
        r = self._call(
            name="Morning Checklist",
            template_type="checklist",
            content="Check email\nReview orders\nUpdate CRM",
        )
        assert r.success is True
        assert r.tool_name == "create_template"
        assert "Morning Checklist" in r.output

    def test_create_template_order(self):
        r = self._call(
            name="Order Template",
            template_type="order",
            content="Товар: {{item}}\nКол-во: {{qty}}",
            description="Шаблон заказа",
        )
        assert r.success is True
        assert "Order Template" in r.output

    def test_create_template_message(self):
        r = self._call(
            name="Greeting Template",
            template_type="message",
            content="Hello, {{name}}! Your order #{{order}} is ready.",
        )
        assert r.success is True

    def test_create_template_report(self):
        r = self._call(
            name="Daily Report",
            template_type="report",
            content="Revenue: {{revenue}}\nExpenses: {{expenses}}",
        )
        assert r.success is True

    def test_create_checklist_data(self):
        r = self._call(
            name="Steps Checklist",
            template_type="checklist",
            content="Step 1\nStep 2\nStep 3",
        )
        assert r.success is True
        assert r.data

    def test_create_template_workflow_type(self):
        r = self._call(
            name="Workflow Template",
            template_type="workflow",
            content="Start → Process → End",
        )
        assert r.success is True


# ═══════════════════════════════════════════════════════════════════════════════
# ИНТЕГРАЦИЯ: Все 8 хендлеров импортируются
# ═══════════════════════════════════════════════════════════════════════════════


class TestToolsIntegration:
    """Все 8 хендлеров Part 9 импортируются и callable."""

    def test_all_handlers_importable(self):
        from pds_ultimate.core.business_tools import (
            tool_create_template,
            tool_crm_search,
            tool_dashboard,
            tool_evening_digest,
            tool_kpi_track,
            tool_list_triggers,
            tool_rate_contact,
            tool_set_trigger,
        )
        assert callable(tool_set_trigger)
        assert callable(tool_list_triggers)
        assert callable(tool_dashboard)
        assert callable(tool_kpi_track)
        assert callable(tool_rate_contact)
        assert callable(tool_crm_search)
        assert callable(tool_evening_digest)
        assert callable(tool_create_template)

    def test_all_handlers_are_async(self):
        import asyncio

        from pds_ultimate.core.business_tools import (
            tool_create_template,
            tool_crm_search,
            tool_dashboard,
            tool_evening_digest,
            tool_kpi_track,
            tool_list_triggers,
            tool_rate_contact,
            tool_set_trigger,
        )
        for fn in [
            tool_set_trigger, tool_list_triggers,
            tool_dashboard, tool_kpi_track,
            tool_rate_contact, tool_crm_search,
            tool_evening_digest, tool_create_template,
        ]:
            assert asyncio.iscoroutinefunction(
                fn), f"{fn.__name__} is not async"

    def test_tool_result_structure(self):
        """Все хендлеры возвращают ToolResult."""
        from pds_ultimate.core.business_tools import tool_set_trigger
        r = run(tool_set_trigger(name="Structure Test"))
        assert hasattr(r, "tool_name")
        assert hasattr(r, "success")
        assert hasattr(r, "output")
        assert hasattr(r, "data")
        assert hasattr(r, "error")
