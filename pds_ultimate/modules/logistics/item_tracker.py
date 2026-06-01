"""
PDS-Ultimate Item Tracker
============================
Трекинг на уровне каждой позиции (Item-Level Tracking).

По ТЗ:
- T+4 дня: Бот спрашивает по КАЖДОЙ позиции: «Позиция #1 (Балаклавы) пришла?»
- Если НЕТ: повтор каждый вторник
- Если ДА: запрос трек-номера → OCR из фото
- Антизабывание: не ответили → через 2 часа, потом вечером
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from pds_ultimate.config import config, logger


class ItemTracker:
    """
    Трекер позиций: проверка статусов, трек-номера, напоминания.
    """

    def __init__(self, db_session_factory):
        self._session_factory = db_session_factory

    # ═══════════════════════════════════════════════════════════════════════
    # Проверка позиций (планировщик вызывает)
    # ═══════════════════════════════════════════════════════════════════════

    async def get_items_to_check(self) -> list[dict]:
        """
        Получить позиции, требующие проверки (next_check_date <= сегодня).
        Вызывается планировщиком (hourly_reminder_check) и вторничной задачей.
        """
        from pds_ultimate.core.database import ItemStatus, Order, OrderItem, OrderStatus

        today = date.today()

        with self._session_factory() as session:
            items = (
                session.query(OrderItem)
                .join(Order)
                .filter(
                    OrderItem.status == ItemStatus.PENDING,
                    OrderItem.next_check_date <= today,
                    Order.status.in_([
                        OrderStatus.CONFIRMED,
                        OrderStatus.TRACKING,
                    ]),
                )
                .all()
            )

            return [
                {
                    "item_id": it.id,
                    "order_id": it.order_id,
                    "order_number": it.order.order_number,
                    "name": it.name,
                    "quantity": it.quantity,
                    "unit": it.unit,
                    "reminder_count": it.reminder_count,
                    "next_check_date": (
                        it.next_check_date.isoformat()
                        if it.next_check_date else None
                    ),
                }
                for it in items
            ]

    async def generate_check_message(self, item: dict) -> str:
        """
        Сгенерировать сообщение-запрос статуса позиции.
        «Позиция #1 (Балаклавы, 500 шт) пришла?»
        """
        msg = (
            f"📦 Заказ #{item['order_number']}\n"
            f"Позиция: {item['name']} ({item['quantity']} {item['unit']})\n"
            f"Пришла? (да/нет)"
        )
        return msg

    # ═══════════════════════════════════════════════════════════════════════
    # Обновление статуса
    # ═══════════════════════════════════════════════════════════════════════

    async def mark_arrived(
        self,
        item_id: int,
        tracking_number: Optional[str] = None,
        tracking_source: str = "manual",
    ) -> dict:
        """Отметить позицию как прибывшую."""
        from pds_ultimate.core.database import ItemStatus, OrderItem

        with self._session_factory() as session:
            item = session.query(OrderItem).filter(
                OrderItem.id == item_id
            ).first()

            if not item:
                return {"error": "Позиция не найдена"}

            item.status = ItemStatus.ARRIVED
            item.arrival_date = date.today()
            item.next_check_date = None

            if tracking_number:
                item.tracking_number = tracking_number
                item.tracking_source = tracking_source

            session.commit()

            logger.info(
                f"Item #{item_id} '{item.name}' marked as ARRIVED"
                + (f", track: {tracking_number}" if tracking_number else "")
            )

            # Проверить — все ли позиции заказа прибыли
            all_arrived = await self._check_all_arrived(item.order_id)

            return {
                "item_id": item.id,
                "name": item.name,
                "status": "arrived",
                "tracking_number": tracking_number,
                "all_items_arrived": all_arrived,
                "order_id": item.order_id,
            }

    async def mark_shipped(
        self,
        item_id: int,
        tracking_number: Optional[str] = None,
    ) -> dict:
        """Отметить позицию как отправленную."""
        from pds_ultimate.core.database import ItemStatus, OrderItem

        with self._session_factory() as session:
            item = session.query(OrderItem).filter(
                OrderItem.id == item_id
            ).first()

            if not item:
                return {"error": "Позиция не найдена"}

            item.status = ItemStatus.SHIPPED

            if tracking_number:
                item.tracking_number = tracking_number

            session.commit()

            return {
                "item_id": item.id,
                "name": item.name,
                "status": "shipped",
                "tracking_number": tracking_number,
            }

    async def set_tracking_number(
        self,
        item_id: int,
        tracking_number: str,
        source: str = "manual",
    ) -> dict:
        """Установить трек-номер для позиции."""
        from pds_ultimate.core.database import OrderItem

        with self._session_factory() as session:
            item = session.query(OrderItem).filter(
                OrderItem.id == item_id
            ).first()

            if not item:
                return {"error": "Позиция не найдена"}

            item.tracking_number = tracking_number
            item.tracking_source = source
            session.commit()

            logger.info(
                f"Item #{item_id}: tracking set to {tracking_number} "
                f"(source: {source})"
            )

            return {
                "item_id": item.id,
                "name": item.name,
                "tracking_number": tracking_number,
                "source": source,
            }

    # ═══════════════════════════════════════════════════════════════════════
    # Антизабывание: перенос следующей проверки
    # ═══════════════════════════════════════════════════════════════════════

    async def postpone_check(self, item_id: int) -> dict:
        """
        Перенести проверку: не ответили → через 2 часа, потом вечером,
        потом следующий вторник.
        """
        from pds_ultimate.core.database import OrderItem

        with self._session_factory() as session:
            item = session.query(OrderItem).filter(
                OrderItem.id == item_id
            ).first()

            if not item:
                return {"error": "Позиция не найдена"}

            item.reminder_count += 1

            now = datetime.now()

            if item.reminder_count == 1:
                # Первый пропуск → через 2 часа
                # Т.к. next_check_date это date, а не datetime,
                # оставляем на сегодня (планировщик проверяет каждый час)
                item.next_check_date = date.today()
            elif item.reminder_count == 2:
                # Второй пропуск → вечером (20:00)
                item.next_check_date = date.today()
            else:
                # Дальше → следующий вторник
                next_tuesday = self._next_weekday(
                    date.today(),
                    config.logistics.recurring_check_weekday,
                )
                item.next_check_date = next_tuesday

            session.commit()

            return {
                "item_id": item.id,
                "name": item.name,
                "reminder_count": item.reminder_count,
                "next_check": (
                    item.next_check_date.isoformat()
                    if item.next_check_date else None
                ),
            }

    async def mark_not_arrived(self, item_id: int) -> dict:
        """
        Пользователь ответил «нет, не пришла».
        Следующая проверка — ближайший вторник.
        """
        from pds_ultimate.core.database import OrderItem

        with self._session_factory() as session:
            item = session.query(OrderItem).filter(
                OrderItem.id == item_id
            ).first()

            if not item:
                return {"error": "Позиция не найдена"}

            next_tuesday = self._next_weekday(
                date.today(),
                config.logistics.recurring_check_weekday,
            )
            item.next_check_date = next_tuesday
            item.reminder_count = 0  # Сбрасываем счётчик (ответ получен)
            session.commit()

            return {
                "item_id": item.id,
                "name": item.name,
                "next_check": next_tuesday.isoformat(),
            }

    # ═══════════════════════════════════════════════════════════════════════
    # Запросы
    # ═══════════════════════════════════════════════════════════════════════

    async def get_pending_items(self, order_id: Optional[int] = None) -> list[dict]:
        """Все ожидающие позиции (опционально по заказу)."""
        from pds_ultimate.core.database import ItemStatus, Order, OrderItem

        with self._session_factory() as session:
            query = (
                session.query(OrderItem)
                .join(Order)
                .filter(OrderItem.status == ItemStatus.PENDING)
            )

            if order_id:
                query = query.filter(OrderItem.order_id == order_id)

            items = query.order_by(OrderItem.next_check_date).all()

            return [
                {
                    "item_id": it.id,
                    "order_id": it.order_id,
                    "order_number": it.order.order_number,
                    "name": it.name,
                    "quantity": it.quantity,
                    "unit": it.unit,
                    "next_check": (
                        it.next_check_date.isoformat()
                        if it.next_check_date else None
                    ),
                }
                for it in items
            ]

    async def get_items_with_tracking(
        self,
        order_id: Optional[int] = None,
    ) -> list[dict]:
        """Позиции с трек-номерами."""
        from pds_ultimate.core.database import Order, OrderItem

        with self._session_factory() as session:
            query = (
                session.query(OrderItem)
                .join(Order)
                .filter(OrderItem.tracking_number.isnot(None))
            )

            if order_id:
                query = query.filter(OrderItem.order_id == order_id)

            items = query.all()

            return [
                {
                    "item_id": it.id,
                    "order_number": it.order.order_number,
                    "name": it.name,
                    "tracking_number": it.tracking_number,
                    "status": it.status.value,
                }
                for it in items
            ]

    # ═══════════════════════════════════════════════════════════════════════
    # Internal
    # ═══════════════════════════════════════════════════════════════════════

    async def _check_all_arrived(self, order_id: int) -> bool:
        """Проверить, все ли позиции заказа прибыли."""
        from pds_ultimate.core.database import ItemStatus, Order, OrderItem, OrderStatus

        with self._session_factory() as session:
            pending_count = (
                session.query(OrderItem)
                .filter(
                    OrderItem.order_id == order_id,
                    OrderItem.status != ItemStatus.ARRIVED,
                    OrderItem.status != ItemStatus.CANCELLED,
                )
                .count()
            )

            if pending_count == 0:
                # Перевести заказ в DELIVERY_CALC
                order = session.query(Order).filter(
                    Order.id == order_id
                ).first()
                if order and order.status == OrderStatus.TRACKING:
                    order.status = OrderStatus.DELIVERY_CALC
                    session.commit()
                    logger.info(
                        f"Order #{order.order_number}: "
                        f"all items arrived → DELIVERY_CALC"
                    )
                return True

            return False

    @staticmethod
    def _next_weekday(from_date: date, weekday: int) -> date:
        """
        Найти ближайший день недели >= from_date.
        weekday: 0=пн, 1=вт, ..., 6=вс
        """
        days_ahead = weekday - from_date.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        return from_date + timedelta(days=days_ahead)

    # ═══════════════════════════════════════════════════════════════════════
    # Вторничный отчёт (вызывается планировщиком)
    # ═══════════════════════════════════════════════════════════════════════

    async def tuesday_status_report(self) -> str:
        """
        Сформировать отчёт по всем позициям, требующим проверки.
        Вызывается планировщиком каждый вторник.
        Возвращает текст для отправки владельцу или "" если нечего проверять.
        """
        items = await self.get_items_to_check()
        if not items:
            return ""

        lines = [f"📦 ВТОРНИЧНАЯ ПРОВЕРКА СТАТУСОВ ({len(items)} позиций)\n"]

        for i, item in enumerate(items, 1):
            track = item.get("tracking_number")
            track_str = f" | трек: {track}" if track else " | без трека"
            days_str = f" | {item.get('days_waiting', '?')} дн."
            lines.append(
                f"{i}. {item.get('name', '?')}{track_str}{days_str}"
            )
            msg = await self.generate_check_message(item)
            if msg:
                lines.append(f"   💬 {msg}")

        lines.append("\nОтветь по каждой позиции: прибыл / в пути / проблема")
        return "\n".join(lines)
