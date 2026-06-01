"""
Тесты жизненного цикла заказа — полный flow.
"""

from datetime import datetime


class TestOrderLifecycle:
    """
    Полный цикл заказа по ТЗ:
    DRAFT → CONFIRMED → TRACKING → DELIVERY_CALC → COMPLETED → ARCHIVED
    """

    def test_order_status_flow(self, db_session):
        """Заказ проходит все статусы."""
        from pds_ultimate.core.database import Order, OrderStatus

        order = Order(
            order_number="ORD-FLOW-001",
            status=OrderStatus.DRAFT,
            income=500.0,
            expense_goods=300.0,
        )
        db_session.add(order)
        db_session.commit()

        # DRAFT → CONFIRMED
        order.status = OrderStatus.CONFIRMED
        db_session.commit()
        assert order.status == OrderStatus.CONFIRMED

        # CONFIRMED → TRACKING
        order.status = OrderStatus.TRACKING
        db_session.commit()
        assert order.status == OrderStatus.TRACKING

        # TRACKING → DELIVERY_CALC
        order.status = OrderStatus.DELIVERY_CALC
        order.delivery_cost = 50.0
        db_session.commit()
        assert order.status == OrderStatus.DELIVERY_CALC

        # DELIVERY_CALC → COMPLETED
        order.status = OrderStatus.COMPLETED
        db_session.commit()
        assert order.status == OrderStatus.COMPLETED

        # COMPLETED → ARCHIVED (все закрытые → архив)
        order.status = OrderStatus.ARCHIVED
        db_session.commit()
        assert order.status == OrderStatus.ARCHIVED

    def test_order_with_items(self, db_session):
        """Заказ с позициями."""
        from pds_ultimate.core.database import ItemStatus, Order, OrderItem, OrderStatus

        order = Order(
            order_number="ORD-ITEMS-001",
            description="Электроника",
            status=OrderStatus.DRAFT,
        )
        db_session.add(order)
        db_session.commit()

        items = [
            OrderItem(order_id=order.id, name="iPhone", quantity=2,
                      unit_price=800.0, status=ItemStatus.PENDING),
            OrderItem(order_id=order.id, name="AirPods", quantity=3,
                      unit_price=150.0, status=ItemStatus.PENDING),
        ]
        db_session.add_all(items)
        db_session.commit()

        # Проверяем связь
        order_items = db_session.query(
            OrderItem).filter_by(order_id=order.id).all()
        assert len(order_items) == 2

        # Товар доставлен
        order_items[0].status = ItemStatus.ARRIVED
        db_session.commit()
        assert order_items[0].status == ItemStatus.ARRIVED

        # Товар отправлен
        order_items[1].status = ItemStatus.SHIPPED
        db_session.commit()
        assert order_items[1].status == ItemStatus.SHIPPED

    def test_order_financial_flow(self, db_session):
        """Финансовый поток заказа."""
        from pds_ultimate.core.database import (
            Order,
            OrderStatus,
            Transaction,
            TransactionType,
        )

        order = Order(
            order_number="ORD-FIN-001",
            description="Товар",
            status=OrderStatus.CONFIRMED,
            income=1000.0,
            expense_goods=500.0,
            delivery_cost=100.0,
        )
        db_session.add(order)
        db_session.commit()

        # Записываем транзакции
        transactions = [
            Transaction(
                order_id=order.id,
                amount=1000.0,
                currency="USD",
                transaction_type=TransactionType.INCOME,
                description="Оплата от клиента",
            ),
            Transaction(
                order_id=order.id,
                amount=500.0,
                currency="USD",
                transaction_type=TransactionType.EXPENSE_GOODS,
                description="Оплата поставщику",
            ),
            Transaction(
                order_id=order.id,
                amount=100.0,
                currency="USD",
                transaction_type=TransactionType.EXPENSE_DELIVERY,
                description="Доставка",
            ),
        ]
        db_session.add_all(transactions)
        db_session.commit()

        # Проверяем
        order_txs = db_session.query(Transaction).filter_by(
            order_id=order.id,
        ).all()
        assert len(order_txs) == 3

        income = sum(t.amount for t in order_txs if t.transaction_type ==
                     TransactionType.INCOME)
        goods = sum(t.amount for t in order_txs if t.transaction_type ==
                    TransactionType.EXPENSE_GOODS)
        delivery = sum(t.amount for t in order_txs if t.transaction_type ==
                       TransactionType.EXPENSE_DELIVERY)

        net_profit = income - goods - delivery
        assert net_profit == 400.0

    def test_calendar_reminder_30min(self, db_session):
        """Напоминание за 30 минут (по ТЗ)."""
        from datetime import timedelta

        from pds_ultimate.core.database import CalendarEvent

        event = CalendarEvent(
            title="Встреча",
            start_time=datetime.utcnow() + timedelta(hours=1),
            end_time=datetime.utcnow() + timedelta(hours=2),
            reminder_minutes=30,
        )
        db_session.add(event)
        db_session.commit()

        assert event.reminder_minutes == 30
