"""
PDS-Ultimate Morning Brief
==============================
Утренний брифинг: 08:30 каждый день.

По ТЗ:
📋 БРИФИНГ НА 08.02.2026
📅 Встречи: 3 (первая в 10:00)
📦 Ожидаем: 2 посылки (Балаклавы — трек CN123, Маски — без трека)
💰 Баланс: $5,430 | Отложено: $2,100
🌤️ Гуанчжоу: +18°, ясно | Задержек рейсов нет
⚠️ Напоминание: Поставщик Ли не ответил 3 дня

Дополнительно:
- Утром даёт план на день
- Спрашивает: «Что добавить или убрать?»
- За 30 минут до события — предупреждение
- Всё хранится в памяти (БД), НЕ Google Calendar
"""

from __future__ import annotations

from datetime import date, datetime, timedelta


class MorningBrief:
    """
    Утренний брифинг: сводка по всем направлениям.
    Вызывается планировщиком в 08:30.
    """

    def __init__(self, db_session_factory):
        self._session_factory = db_session_factory

    async def generate(self) -> str:
        """
        Сгенерировать полный утренний брифинг.
        Возвращает форматированный текст.
        """
        today = date.today()
        sections = []

        sections.append(
            f"📋 БРИФИНГ НА {today.strftime('%d.%m.%Y')}\n"
        )

        # 1. Календарь
        calendar_section = await self._calendar_section()
        if calendar_section:
            sections.append(calendar_section)

        # 2. Логистика
        logistics_section = await self._logistics_section()
        if logistics_section:
            sections.append(logistics_section)

        # 3. Финансы
        finance_section = await self._finance_section()
        if finance_section:
            sections.append(finance_section)

        # 4. Напоминания / предупреждения
        alerts_section = await self._alerts_section()
        if alerts_section:
            sections.append(alerts_section)

        # 5. Спрашиваем что добавить/убрать
        sections.append(
            "\n💬 Что добавить или убрать из плана на сегодня?"
        )

        return "\n".join(sections)

    async def generate_plan_summary(self) -> str:
        """
        Краткий план дня — только события.
        Используется при повторном запросе «покажи план».
        """
        events = await self._calendar_section()
        if not events:
            return "📅 На сегодня событий нет.\n\n💬 Хочешь что-нибудь запланировать?"
        return f"{events}\n\n💬 Что добавить или убрать?"

    # ═══════════════════════════════════════════════════════════════════════
    # Секции брифинга
    # ═══════════════════════════════════════════════════════════════════════

    async def _calendar_section(self) -> str:
        """Секция: встречи на сегодня."""
        from pds_ultimate.core.database import CalendarEvent, TaskStatus

        today = date.today()
        start = datetime.combine(today, datetime.min.time())
        end = start + timedelta(days=1)

        with self._session_factory() as session:
            events = (
                session.query(CalendarEvent)
                .filter(
                    CalendarEvent.start_time >= start,
                    CalendarEvent.start_time < end,
                    CalendarEvent.status != TaskStatus.CANCELLED,
                )
                .order_by(CalendarEvent.start_time)
                .all()
            )

            if not events:
                return "📅 Встречи: нет запланированных"

            first = events[0].start_time.strftime("%H:%M")
            line = f"📅 Встречи: {len(events)} (первая в {first})"

            for e in events:
                line += (
                    f"\n   • {e.start_time.strftime('%H:%M')} — {e.title}"
                    + (f" 📍{e.location}" if e.location else "")
                )

            return line

    async def _logistics_section(self) -> str:
        """Секция: ожидаемые посылки."""
        from pds_ultimate.core.database import (
            ItemStatus,
            Order,
            OrderItem,
            OrderStatus,
        )

        with self._session_factory() as session:
            # Pending + Shipped items
            items = (
                session.query(OrderItem)
                .join(Order)
                .filter(
                    OrderItem.status.in_([
                        ItemStatus.PENDING, ItemStatus.SHIPPED,
                    ]),
                    Order.status.in_([
                        OrderStatus.CONFIRMED,
                        OrderStatus.TRACKING,
                    ]),
                )
                .all()
            )

            if not items:
                return "📦 Ожидаем: всё получено ✅"

            line = f"📦 Ожидаем: {len(items)} позиций"

            for it in items[:5]:  # Первые 5
                track = f"трек {it.tracking_number}" if it.tracking_number else "без трека"
                line += f"\n   • {it.name} — {track}"

            if len(items) > 5:
                line += f"\n   ... и ещё {len(items) - 5}"

            # Позиции с просроченной проверкой
            today = date.today()
            overdue = [
                it for it in items
                if it.next_check_date and it.next_check_date <= today
            ]
            if overdue:
                line += f"\n   ⚠️ Требуют проверки: {len(overdue)}"

            return line

    async def _finance_section(self) -> str:
        """Секция: финансовый баланс."""
        from sqlalchemy import func

        from pds_ultimate.core.database import Transaction, TransactionType

        with self._session_factory() as session:
            def _sum_type(tx_type: TransactionType) -> float:
                result = (
                    session.query(func.sum(Transaction.amount_usd))
                    .filter(Transaction.transaction_type == tx_type)
                    .scalar()
                )
                return result or 0.0

            total_income = _sum_type(TransactionType.INCOME)
            total_goods = _sum_type(TransactionType.EXPENSE_GOODS)
            total_delivery = _sum_type(TransactionType.EXPENSE_DELIVERY)
            total_personal = _sum_type(TransactionType.EXPENSE_PERSONAL)
            total_savings = _sum_type(TransactionType.PROFIT_SAVINGS)
            total_expenses_alloc = _sum_type(TransactionType.PROFIT_EXPENSES)

            net_profit = total_income - total_goods - total_delivery
            available = total_expenses_alloc - total_personal

            return (
                f"💰 Баланс: ${available:,.0f} | "
                f"Отложено: ${total_savings:,.0f} | "
                f"Прибыль: ${net_profit:,.0f}"
            )

    async def _alerts_section(self) -> str:
        """Секция: предупреждения и напоминания."""
        from pds_ultimate.core.database import Reminder, ReminderStatus

        today = date.today()
        alerts = []

        with self._session_factory() as session:
            # Непрочитанные напоминания
            pending_reminders = (
                session.query(Reminder)
                .filter(
                    Reminder.status == ReminderStatus.PENDING,
                    Reminder.scheduled_at <= datetime.now(),
                )
                .count()
            )

            if pending_reminders > 0:
                alerts.append(
                    f"🔔 Непрочитанных напоминаний: {pending_reminders}"
                )

        if not alerts:
            return ""

        return "\n".join(["⚠️ Внимание:"] + [f"   {a}" for a in alerts])

    # ═══════════════════════════════════════════════════════════════════════
    # 3-дневный отчёт (email)
    # ═══════════════════════════════════════════════════════════════════════

    async def generate_3day_report(self) -> str:
        """
        Отчёт за последние 3 дня (отправляется на email по ТЗ).
        """
        from pds_ultimate.core.database import (
            Order,
            OrderStatus,
            Transaction,
            TransactionType,
        )

        three_days_ago = date.today() - timedelta(days=3)

        with self._session_factory() as session:
            # Транзакции за 3 дня
            recent_txs = (
                session.query(Transaction)
                .filter(Transaction.transaction_date >= three_days_ago)
                .order_by(Transaction.transaction_date.desc())
                .all()
            )

            # Новые заказы
            new_orders = (
                session.query(Order)
                .filter(Order.order_date >= three_days_ago)
                .count()
            )

            # Закрытые заказы
            closed_orders = (
                session.query(Order)
                .filter(
                    Order.completed_date >= three_days_ago,
                    Order.status.in_([
                        OrderStatus.COMPLETED, OrderStatus.ARCHIVED,
                    ]),
                )
                .count()
            )

        lines = [
            f"📊 ОТЧЁТ ЗА 3 ДНЯ "
            f"({three_days_ago.strftime('%d.%m')}–{date.today().strftime('%d.%m.%Y')})\n",
            f"📦 Новых заказов: {new_orders}",
            f"✅ Закрытых заказов: {closed_orders}",
            f"💳 Транзакций: {len(recent_txs)}",
        ]

        if recent_txs:
            total_income = sum(
                tx.amount_usd or 0 for tx in recent_txs
                if tx.transaction_type == TransactionType.INCOME
            )
            total_expense = sum(
                tx.amount_usd or 0 for tx in recent_txs
                if tx.transaction_type in (
                    TransactionType.EXPENSE_GOODS,
                    TransactionType.EXPENSE_DELIVERY,
                    TransactionType.EXPENSE_PERSONAL,
                )
            )

            lines.append(f"\n💰 Доход: ${total_income:,.2f}")
            lines.append(f"💸 Расход: ${total_expense:,.2f}")
            lines.append(
                f"📈 Нетто: ${total_income - total_expense:,.2f}"
            )

        return "\n".join(lines)
