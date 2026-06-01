"""
Тесты базы данных — database.py
"""

from datetime import datetime, timedelta


class TestDatabaseModels:
    """Тесты моделей БД."""

    def test_create_order(self, db_session):
        """Создание заказа."""
        from pds_ultimate.core.database import Order, OrderStatus

        order = Order(
            order_number="ORD-TEST-001",
            status=OrderStatus.DRAFT,
            income=1000.0,
            expense_goods=500.0,
        )
        db_session.add(order)
        db_session.commit()

        assert order.id is not None
        assert order.status == OrderStatus.DRAFT
        assert order.income == 1000.0

    def test_order_statuses(self):
        """Все статусы заказа присутствуют."""
        from pds_ultimate.core.database import OrderStatus

        expected = {"DRAFT", "CONFIRMED", "TRACKING",
                    "DELIVERY_CALC", "COMPLETED", "ARCHIVED"}
        actual = {s.name for s in OrderStatus}
        assert expected == actual

    def test_item_statuses(self):
        """Все статусы товара присутствуют (включая SHIPPED и CANCELLED)."""
        from pds_ultimate.core.database import ItemStatus

        expected = {"PENDING", "ARRIVED",
                    "TRACK_REQUESTED", "SHIPPED", "CANCELLED"}
        actual = {s.name for s in ItemStatus}
        assert expected == actual

    def test_transaction_types(self):
        """Все типы транзакций (PROFIT_EXPENSES — множественное число)."""
        from pds_ultimate.core.database import TransactionType

        expected = {
            "INCOME", "EXPENSE_GOODS", "EXPENSE_DELIVERY",
            "EXPENSE_PERSONAL", "PROFIT_EXPENSES", "PROFIT_SAVINGS",
        }
        actual = {t.name for t in TransactionType}
        assert expected == actual

    def test_transaction_type_profit_expenses_plural(self):
        """PROFIT_EXPENSES — именно множественное число (не PROFIT_EXPENSE)."""
        from pds_ultimate.core.database import TransactionType

        assert hasattr(TransactionType, "PROFIT_EXPENSES")
        # Проверяем что нет единственного числа
        assert not hasattr(TransactionType, "PROFIT_EXPENSE")

    def test_reminder_status(self):
        """Статусы напоминаний."""
        from pds_ultimate.core.database import ReminderStatus

        expected = {"PENDING", "SENT", "ANSWERED", "ESCALATED"}
        actual = {s.name for s in ReminderStatus}
        assert expected == actual

    def test_task_status(self):
        """Статусы задач."""
        from pds_ultimate.core.database import TaskStatus

        expected = {"PENDING", "IN_PROGRESS", "COMPLETED", "CANCELLED"}
        actual = {s.name for s in TaskStatus}
        assert expected == actual

    def test_create_item(self, db_session):
        """Создание товара."""
        from pds_ultimate.core.database import ItemStatus, Order, OrderItem, OrderStatus

        order = Order(
            order_number="ORD-ITEM-001",
            status=OrderStatus.DRAFT,
        )
        db_session.add(order)
        db_session.commit()

        item = OrderItem(
            order_id=order.id,
            name="Позиция 1",
            quantity=5,
            unit_price=100.0,
            status=ItemStatus.PENDING,
        )
        db_session.add(item)
        db_session.commit()

        assert item.id is not None
        assert item.order_id == order.id
        assert item.quantity == 5

    def test_create_transaction(self, db_session):
        """Создание финансовой транзакции."""
        from pds_ultimate.core.database import Transaction, TransactionType

        tx = Transaction(
            amount=1000.0,
            currency="USD",
            transaction_type=TransactionType.INCOME,
            description="Оплата от клиента",
        )
        db_session.add(tx)
        db_session.commit()

        assert tx.id is not None
        assert tx.transaction_type == TransactionType.INCOME
        assert tx.amount == 1000.0

    def test_create_calendar_event(self, db_session):
        """Создание события календаря (без google_event_id)."""
        from pds_ultimate.core.database import CalendarEvent

        event = CalendarEvent(
            title="Встреча с клиентом",
            start_time=datetime.utcnow(),
            end_time=datetime.utcnow() + timedelta(hours=1),
            reminder_minutes=30,
        )
        db_session.add(event)
        db_session.commit()

        assert event.id is not None
        assert event.reminder_minutes == 30
        assert event.title == "Встреча с клиентом"
        # Нет google_event_id — календарь в БД
        assert not hasattr(event, "google_event_id")

    def test_create_reminder(self, db_session):
        """Создание напоминания (поле message, не text)."""
        from pds_ultimate.core.database import Reminder, ReminderStatus

        rem = Reminder(
            message="Не забыть позвонить",
            scheduled_at=datetime.utcnow() + timedelta(hours=2),
            status=ReminderStatus.PENDING,
            reminder_type="general",
        )
        db_session.add(rem)
        db_session.commit()

        assert rem.id is not None
        assert rem.message == "Не забыть позвонить"
        assert rem.status == ReminderStatus.PENDING
        # Поле message, не text
        assert hasattr(rem, "message")

    def test_create_communication_style(self, db_session):
        """Профиль стиля общения."""
        from pds_ultimate.core.database import CommunicationStyle

        style = CommunicationStyle(
            style_profile='{"tone": "friendly"}',
            tg_chats_analyzed=7,
            wa_chats_analyzed=3,
            total_messages_analyzed=500,
            system_prompt="Пиши дружелюбно",
            is_active=True,
            last_scan_date=datetime.utcnow(),
        )
        db_session.add(style)
        db_session.commit()

        assert style.id is not None
        assert style.is_active is True
        assert style.tg_chats_analyzed == 7


class TestDatabaseInit:
    """Тесты инициализации БД."""

    def test_init_database(self):
        """init_database возвращает engine и session_factory."""
        import os
        import tempfile

        from pds_ultimate.core.database import init_database

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_path = f.name

        try:
            engine, session_factory = init_database(db_path=tmp_path)
            assert engine is not None
            assert session_factory is not None

            # Проверяем что сессию можно создать
            session = session_factory()
            session.close()
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
