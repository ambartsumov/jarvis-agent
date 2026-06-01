"""
Тесты Smart Triggers (Part 9)
===================================
TriggerCondition, Trigger, TriggerEvaluator, AlertHistory,
NotificationRouter, TriggerChain, TriggerTemplates, TriggerManager.
~60 тестов.
"""


from pds_ultimate.core.smart_triggers import (
    Alert,
    AlertChannel,
    AlertHistory,
    AlertSeverity,
    ComparisonOp,
    NotificationRouter,
    Trigger,
    TriggerChain,
    TriggerCondition,
    TriggerEvaluator,
    TriggerManager,
    TriggerStatus,
    TriggerTemplates,
    TriggerType,
    trigger_manager,
)

# ═══════════════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════════════


class TestEnums:
    """Enum smoke tests."""

    def test_trigger_type_values(self):
        assert TriggerType.THRESHOLD.value == "threshold"
        assert TriggerType.SILENCE.value == "silence"
        assert TriggerType.SCHEDULE.value == "schedule"
        assert TriggerType.CUSTOM.value == "custom"
        assert TriggerType.EXCHANGE_RATE.value == "exchange_rate"
        assert TriggerType.BALANCE.value == "balance"

    def test_trigger_status_values(self):
        assert TriggerStatus.ACTIVE.value == "active"
        assert TriggerStatus.PAUSED.value == "paused"
        assert TriggerStatus.MUTED.value == "muted"
        assert TriggerStatus.FIRED.value == "fired"
        assert TriggerStatus.EXPIRED.value == "expired"

    def test_comparison_op_values(self):
        ops = [">", ">=", "<", "<=", "==", "!="]
        for op in ops:
            assert ComparisonOp(op) is not None

    def test_alert_severity_values(self):
        assert AlertSeverity.INFO.value == "info"
        assert AlertSeverity.WARNING.value == "warning"
        assert AlertSeverity.CRITICAL.value == "critical"
        assert AlertSeverity.EMERGENCY.value == "emergency"

    def test_alert_channel_values(self):
        assert AlertChannel.TELEGRAM.value == "telegram"
        assert AlertChannel.LOG.value == "log"


# ═══════════════════════════════════════════════════════════════════════════════
# TriggerCondition
# ═══════════════════════════════════════════════════════════════════════════════


class TestTriggerCondition:
    """TriggerCondition — условие триггера."""

    def test_create(self):
        c = TriggerCondition(
            field="balance", operator=ComparisonOp.LT, value=100)
        assert c.field == "balance"
        assert c.operator == ComparisonOp.LT
        assert c.value == 100

    def test_evaluate_gt_true(self):
        c = TriggerCondition(field="price", operator=ComparisonOp.GT, value=50)
        assert c.evaluate(60) is True

    def test_evaluate_gt_false(self):
        c = TriggerCondition(field="price", operator=ComparisonOp.GT, value=50)
        assert c.evaluate(40) is False

    def test_evaluate_gte(self):
        c = TriggerCondition(field="x", operator=ComparisonOp.GTE, value=10)
        assert c.evaluate(10) is True
        assert c.evaluate(9) is False

    def test_evaluate_lt(self):
        c = TriggerCondition(field="x", operator=ComparisonOp.LT, value=5)
        assert c.evaluate(3) is True
        assert c.evaluate(5) is False

    def test_evaluate_lte(self):
        c = TriggerCondition(field="x", operator=ComparisonOp.LTE, value=5)
        assert c.evaluate(5) is True
        assert c.evaluate(6) is False

    def test_evaluate_eq(self):
        c = TriggerCondition(field="x", operator=ComparisonOp.EQ, value=42)
        assert c.evaluate(42) is True
        assert c.evaluate(43) is False

    def test_evaluate_neq(self):
        c = TriggerCondition(field="x", operator=ComparisonOp.NEQ, value=0)
        assert c.evaluate(1) is True
        assert c.evaluate(0) is False

    def test_evaluate_invalid_type(self):
        c = TriggerCondition(
            field="missing", operator=ComparisonOp.GT, value=0)
        assert c.evaluate(None) is False

    def test_describe(self):
        c = TriggerCondition(field="rate", operator=ComparisonOp.GT, value=20)
        desc = c.describe()
        assert "rate" in desc
        assert "20" in desc

    def test_to_dict(self):
        c = TriggerCondition(field="x", operator=ComparisonOp.LT, value=5)
        d = c.to_dict()
        assert d["field"] == "x"
        assert d["operator"] == "<"
        assert d["value"] == 5


# ═══════════════════════════════════════════════════════════════════════════════
# Alert
# ═══════════════════════════════════════════════════════════════════════════════


class TestAlert:
    """Alert — уведомление."""

    def test_create(self):
        a = Alert(
            trigger_id="t1",
            trigger_name="Test",
            severity=AlertSeverity.WARNING,
            message="Something happened",
        )
        assert a.trigger_id == "t1"
        assert a.severity == AlertSeverity.WARNING
        assert a.id

    def test_format_message(self):
        a = Alert(
            trigger_id="t1",
            trigger_name="Цена",
            severity=AlertSeverity.CRITICAL,
            message="Цена упала",
        )
        msg = a.format_message()
        assert "Цена" in msg

    def test_to_dict(self):
        a = Alert(
            trigger_id="t1",
            trigger_name="Test",
            severity=AlertSeverity.INFO,
            message="test",
        )
        d = a.to_dict()
        assert d["trigger_name"] == "Test"
        assert d["severity"] == "info"
        assert "id" in d


# ═══════════════════════════════════════════════════════════════════════════════
# Trigger
# ═══════════════════════════════════════════════════════════════════════════════


class TestTrigger:
    """Trigger — полный триггер."""

    def _make_trigger(self, **kwargs):
        defaults = dict(
            name="Test trigger",
            trigger_type=TriggerType.THRESHOLD,
            condition=TriggerCondition(
                field="price", operator=ComparisonOp.GT, value=100,
            ),
            severity=AlertSeverity.WARNING,
        )
        defaults.update(kwargs)
        return Trigger(**defaults)

    def test_create(self):
        t = self._make_trigger()
        assert t.name == "Test trigger"
        assert t.status == TriggerStatus.ACTIVE
        assert t.fire_count == 0

    def test_fire_returns_alert(self):
        t = self._make_trigger()
        alert = t.fire(current_value=150, message="Price high")
        assert t.fire_count == 1
        assert t.last_fired is not None
        assert isinstance(alert, Alert)

    def test_multiple_fires(self):
        t = self._make_trigger()
        t.fire()
        t.fire()
        t.fire()
        assert t.fire_count == 3

    def test_pause_resume(self):
        t = self._make_trigger()
        t.pause()
        assert t.status == TriggerStatus.PAUSED
        t.resume()
        assert t.status == TriggerStatus.ACTIVE

    def test_snooze_sets_muted_until(self):
        t = self._make_trigger()
        t.snooze(minutes=30)
        assert t.muted_until is not None

    def test_is_active_true(self):
        t = self._make_trigger()
        assert t.is_active is True

    def test_is_active_paused(self):
        t = self._make_trigger()
        t.pause()
        assert t.is_active is False

    def test_can_fire_active(self):
        t = self._make_trigger()
        assert t.can_fire() is True

    def test_can_fire_snoozed(self):
        t = self._make_trigger()
        t.snooze(minutes=30)
        assert t.can_fire() is False

    def test_to_dict(self):
        t = self._make_trigger()
        d = t.to_dict()
        assert d["name"] == "Test trigger"
        assert "id" in d
        assert d["status"] == "active"
        assert d["fire_count"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# TriggerEvaluator
# ═══════════════════════════════════════════════════════════════════════════════


class TestTriggerEvaluator:
    """TriggerEvaluator — вычисление триггеров."""

    def test_evaluate_trigger_true(self):
        ev = TriggerEvaluator()
        t = Trigger(
            name="High price",
            trigger_type=TriggerType.THRESHOLD,
            condition=TriggerCondition(
                field="price", operator=ComparisonOp.GT, value=100,
            ),
        )
        fired, value = ev.evaluate_trigger(t, {"price": 150})
        assert fired is True
        assert value == 150

    def test_evaluate_trigger_false(self):
        ev = TriggerEvaluator()
        t = Trigger(
            name="Low price",
            trigger_type=TriggerType.THRESHOLD,
            condition=TriggerCondition(
                field="price", operator=ComparisonOp.LT, value=50,
            ),
        )
        fired, value = ev.evaluate_trigger(t, {"price": 100})
        assert fired is False

    def test_evaluate_no_condition(self):
        ev = TriggerEvaluator()
        t = Trigger(name="No cond", trigger_type=TriggerType.THRESHOLD)
        fired, value = ev.evaluate_trigger(t, {"x": 1})
        assert fired is False

    def test_evaluate_with_provider(self):
        ev = TriggerEvaluator()
        # rate_usd_tmt is a default provider → returns 19.5
        t = Trigger(
            name="TMT rate",
            trigger_type=TriggerType.EXCHANGE_RATE,
            condition=TriggerCondition(
                field="rate_usd_tmt", operator=ComparisonOp.GT, value=19.0,
            ),
        )
        fired, value = ev.evaluate_trigger(t, {})
        assert fired is True
        assert value == 19.5


# ═══════════════════════════════════════════════════════════════════════════════
# AlertHistory
# ═══════════════════════════════════════════════════════════════════════════════


class TestAlertHistory:
    """AlertHistory — история алертов."""

    def test_empty(self):
        h = AlertHistory()
        assert h.get_recent(5) == []
        assert h.get_stats()["total"] == 0

    def test_add_and_get(self):
        h = AlertHistory()
        a = Alert(
            trigger_id="t1", trigger_name="Test",
            severity=AlertSeverity.WARNING, message="test",
        )
        h.add(a)
        assert len(h.get_recent(5)) == 1
        assert h.get_stats()["total"] == 1

    def test_limit_recent(self):
        h = AlertHistory()
        for i in range(20):
            h.add(Alert(
                trigger_id=f"t{i}", trigger_name=f"T{i}",
                severity=AlertSeverity.INFO, message=f"msg{i}",
            ))
        recent = h.get_recent(5)
        assert len(recent) == 5

    def test_get_by_trigger(self):
        h = AlertHistory()
        h.add(Alert(trigger_id="t1", trigger_name="A",
                    severity=AlertSeverity.INFO, message="a"))
        h.add(Alert(trigger_id="t2", trigger_name="B",
                    severity=AlertSeverity.INFO, message="b"))
        h.add(Alert(trigger_id="t1", trigger_name="A",
                    severity=AlertSeverity.INFO, message="a2"))
        by_t1 = h.get_by_trigger("t1")
        assert len(by_t1) == 2

    def test_stats_by_severity(self):
        h = AlertHistory()
        h.add(Alert(trigger_id="t1", trigger_name="A",
                    severity=AlertSeverity.WARNING, message="w"))
        h.add(Alert(trigger_id="t2", trigger_name="B",
                    severity=AlertSeverity.CRITICAL, message="c"))
        stats = h.get_stats()
        assert stats["by_severity"]["warning"] == 1
        assert stats["by_severity"]["critical"] == 1

    def test_total_property(self):
        h = AlertHistory()
        assert h.total == 0
        h.add(Alert(trigger_id="t1", trigger_name="A",
                    severity=AlertSeverity.INFO, message="m"))
        assert h.total == 1


# ═══════════════════════════════════════════════════════════════════════════════
# NotificationRouter
# ═══════════════════════════════════════════════════════════════════════════════


class TestNotificationRouter:
    """NotificationRouter — маршрутизация уведомлений."""

    def test_create(self):
        r = NotificationRouter()
        assert r is not None

    def test_get_channels_for_alert(self):
        r = NotificationRouter()
        a = Alert(
            trigger_id="t1", trigger_name="Test",
            severity=AlertSeverity.EMERGENCY, message="fire!",
        )
        channels = r.get_channels_for_alert(a)
        assert isinstance(channels, list)
        assert len(channels) > 0

    def test_info_goes_to_log(self):
        r = NotificationRouter()
        a = Alert(
            trigger_id="t1", trigger_name="Test",
            severity=AlertSeverity.INFO, message="info",
        )
        channels = r.get_channels_for_alert(a)
        assert AlertChannel.LOG in channels


# ═══════════════════════════════════════════════════════════════════════════════
# TriggerChain
# ═══════════════════════════════════════════════════════════════════════════════


class TestTriggerChain:
    """TriggerChain — цепочка триггеров."""

    def test_create(self):
        chain = TriggerChain()
        assert len(chain.get_all_chains()) == 0

    def test_add_chain(self):
        chain = TriggerChain()
        chain.add_chain("t1", "t2")
        chain.add_chain("t1", "t3")
        targets = chain.get_chain_targets("t1")
        assert len(targets) == 2
        assert "t2" in targets
        assert "t3" in targets

    def test_has_chain(self):
        chain = TriggerChain()
        assert chain.has_chain("t1") is False
        chain.add_chain("t1", "t2")
        assert chain.has_chain("t1") is True

    def test_remove_chain(self):
        chain = TriggerChain()
        chain.add_chain("t1", "t2")
        assert chain.remove_chain("t1", "t2") is True
        assert chain.has_chain("t1") is False

    def test_detect_cycle(self):
        chain = TriggerChain()
        chain.add_chain("t1", "t2")
        chain.add_chain("t2", "t3")
        assert chain.detect_cycle("t1", "t3") is False
        chain.add_chain("t3", "t1")
        assert chain.detect_cycle("t1", "t2") is True


# ═══════════════════════════════════════════════════════════════════════════════
# TriggerTemplates
# ═══════════════════════════════════════════════════════════════════════════════


class TestTriggerTemplates:
    """TriggerTemplates — готовые шаблоны."""

    def test_exchange_rate_alert(self):
        t = TriggerTemplates.exchange_rate_alert(threshold=20.0)
        assert t.name
        assert t.condition is not None
        assert t.condition.value == 20.0

    def test_balance_alert(self):
        t = TriggerTemplates.balance_alert(threshold=500)
        assert t.condition.field == "balance"
        assert t.severity == AlertSeverity.CRITICAL

    def test_supplier_silence_alert(self):
        t = TriggerTemplates.supplier_silence_alert(supplier_name="Али")
        assert "Али" in t.name

    def test_deadline_alert(self):
        t = TriggerTemplates.deadline_alert()
        assert t.trigger_type == TriggerType.DEADLINE

    def test_price_change_alert(self):
        t = TriggerTemplates.price_change_alert(item_name="Товар")
        assert t.condition is not None
        assert "Товар" in t.name

    def test_get_templates_dict(self):
        templates = TriggerTemplates.get_templates()
        assert "exchange_rate" in templates
        assert "balance" in templates
        assert "price_change" in templates


# ═══════════════════════════════════════════════════════════════════════════════
# TriggerManager
# ═══════════════════════════════════════════════════════════════════════════════


class TestTriggerManager:
    """TriggerManager — основной менеджер."""

    def test_create_trigger(self):
        mgr = TriggerManager()
        t = mgr.create_trigger(name="MyTrig", trigger_type="threshold")
        assert t.name == "MyTrig"
        assert mgr.get_trigger(t.id) is t

    def test_create_from_template(self):
        mgr = TriggerManager()
        t = mgr.create_from_template("exchange_rate", threshold=21.0)
        assert t is not None
        assert t.condition.value == 21.0

    def test_create_from_template_balance(self):
        mgr = TriggerManager()
        t = mgr.create_from_template("balance", threshold=200)
        assert t.condition.field == "balance"

    def test_create_from_template_unknown(self):
        mgr = TriggerManager()
        try:
            mgr.create_from_template("nonexistent_template_xyz")
            assert False, "Should raise ValueError"
        except ValueError:
            pass

    def test_get_by_name(self):
        mgr = TriggerManager()
        mgr.create_trigger(name="FindMe", trigger_type="threshold")
        found = mgr.get_by_name("FindMe")
        assert found is not None
        assert found.name == "FindMe"

    def test_get_by_name_not_found(self):
        mgr = TriggerManager()
        assert mgr.get_by_name("NonExist") is None

    def test_get_triggers(self):
        mgr = TriggerManager()
        mgr.create_trigger(name="A", trigger_type="threshold")
        mgr.create_trigger(name="B", trigger_type="threshold")
        all_t = mgr.get_triggers()
        assert len(all_t) == 2

    def test_get_active_triggers(self):
        mgr = TriggerManager()
        t1 = mgr.create_trigger(name="Active1", trigger_type="threshold")
        t2 = mgr.create_trigger(name="Paused1", trigger_type="threshold")
        mgr.pause_trigger(t2.id)
        active = mgr.get_active_triggers()
        assert len(active) == 1
        assert active[0].name == "Active1"

    def test_delete_trigger(self):
        mgr = TriggerManager()
        t = mgr.create_trigger(name="ToDelete", trigger_type="threshold")
        assert mgr.delete_trigger(t.id) is True
        assert mgr.get_trigger(t.id) is None

    def test_delete_nonexistent(self):
        mgr = TriggerManager()
        assert mgr.delete_trigger("fake-id") is False

    def test_pause_trigger(self):
        mgr = TriggerManager()
        t = mgr.create_trigger(name="P", trigger_type="threshold")
        mgr.pause_trigger(t.id)
        assert t.status == TriggerStatus.PAUSED

    def test_resume_trigger(self):
        mgr = TriggerManager()
        t = mgr.create_trigger(name="R", trigger_type="threshold")
        mgr.pause_trigger(t.id)
        mgr.resume_trigger(t.id)
        assert t.status == TriggerStatus.ACTIVE

    def test_snooze_trigger(self):
        mgr = TriggerManager()
        t = mgr.create_trigger(name="S", trigger_type="threshold")
        mgr.snooze_trigger(t.id, minutes=60)
        assert t.muted_until is not None

    def test_check_trigger_fires(self):
        mgr = TriggerManager()
        cond = TriggerCondition(
            field="price", operator=ComparisonOp.GT, value=100,
        )
        t = mgr.create_trigger(
            name="PriceHigh", trigger_type="threshold", condition=cond,
        )
        alert = mgr.check_trigger(t.id, {"price": 150})
        assert alert is not None
        assert t.fire_count == 1

    def test_check_trigger_no_fire(self):
        mgr = TriggerManager()
        cond = TriggerCondition(
            field="price", operator=ComparisonOp.GT, value=100,
        )
        t = mgr.create_trigger(
            name="PriceLow", trigger_type="threshold", condition=cond,
        )
        alert = mgr.check_trigger(t.id, {"price": 50})
        assert alert is None
        assert t.fire_count == 0

    def test_check_all(self):
        mgr = TriggerManager()
        cond1 = TriggerCondition(
            field="x", operator=ComparisonOp.GT, value=10,
        )
        cond2 = TriggerCondition(
            field="x", operator=ComparisonOp.LT, value=5,
        )
        mgr.create_trigger(
            name="High", trigger_type="threshold", condition=cond1)
        mgr.create_trigger(
            name="Low", trigger_type="threshold", condition=cond2)
        alerts = mgr.check_all({"x": 15})
        assert len(alerts) == 1
        assert alerts[0].trigger_name == "High"

    def test_get_stats(self):
        mgr = TriggerManager()
        mgr.create_trigger(name="S1", trigger_type="threshold")
        mgr.create_trigger(name="S2", trigger_type="threshold")
        stats = mgr.get_stats()
        assert stats["total"] == 2
        assert stats["active"] == 2

    def test_format_triggers_list(self):
        mgr = TriggerManager()
        mgr.create_trigger(name="Format1", trigger_type="threshold")
        mgr.create_trigger(name="Format2", trigger_type="threshold")
        text = mgr.format_triggers_list()
        assert "Format1" in text
        assert "Format2" in text

    def test_format_triggers_list_empty(self):
        mgr = TriggerManager()
        text = mgr.format_triggers_list()
        assert isinstance(text, str)

    def test_global_instance(self):
        assert trigger_manager is not None
        assert isinstance(trigger_manager, TriggerManager)
