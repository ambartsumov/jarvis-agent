"""
PDS-Ultimate Order Manager
==============================
Полный жизненный цикл заказа.

По ТЗ:
  DRAFT → CONFIRMED → TRACKING → DELIVERY_CALC → COMPLETED → ARCHIVED

Фазы:
  1. Создание: парсинг позиций, сохранение в БД + временный Excel
  2. Сопровождение: T+4 дня → запрос по каждой позиции → вторники → трек
  3. Закрытие: все прибыли → доставка → чистая прибыль → распределение → архив
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from pds_ultimate.config import config, logger


class OrderManager:
    """
    Менеджер заказов: создание, обновление статуса, закрытие.
    """

    def __init__(self, db_session_factory):
        self._session_factory = db_session_factory

    # ═══════════════════════════════════════════════════════════════════════
    # Фаза 1: Создание заказа
    # ═══════════════════════════════════════════════════════════════════════

    async def create_order(
        self,
        items: list[dict],
        supplier_name: Optional[str] = None,
        client_name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> dict:
        """
        Создать новый заказ из распарсенных позиций.

        items: [{"name": "Балаклавы", "quantity": 500, "unit": "шт",
                 "unit_price": 2.5, "price_currency": "USD", "weight": 10.0}]

        Возвращает: {"order_id": ..., "order_number": ..., "items_count": ...}
        """
        from pds_ultimate.core.database import (
            ContactType,
            ItemStatus,
            Order,
            OrderItem,
            OrderStatus,
        )

        with self._session_factory() as session:
            # Генерация номера заказа
            order_number = await self._generate_order_number(session)

            # Поиск/создание контрагентов
            supplier_id = None
            client_id = None

            if supplier_name:
                supplier_id = await self._find_or_create_contact(
                    session, supplier_name, ContactType.SUPPLIER
                )

            if client_name:
                client_id = await self._find_or_create_contact(
                    session, client_name, ContactType.CLIENT
                )

            # Дата первой проверки: T + first_status_check_days
            first_check = date.today() + timedelta(
                days=config.logistics.first_status_check_days
            )

            # Создание заказа
            order = Order(
                order_number=order_number,
                status=OrderStatus.DRAFT,
                supplier_id=supplier_id,
                client_id=client_id,
                description=description,
                order_date=date.today(),
            )
            session.add(order)
            session.flush()  # получаем order.id

            # Создание позиций
            created_items = []
            for item_data in items:
                item = OrderItem(
                    order_id=order.id,
                    name=item_data.get("name", "Без названия"),
                    quantity=float(item_data.get("quantity", 1)),
                    unit=item_data.get("unit", "шт"),
                    unit_price=item_data.get("unit_price"),
                    price_currency=item_data.get("price_currency", "USD"),
                    weight=item_data.get("weight"),
                    status=ItemStatus.PENDING,
                    next_check_date=first_check,
                )
                session.add(item)
                created_items.append(item)

            session.commit()

            logger.info(
                f"Order created: #{order.order_number} "
                f"with {len(created_items)} items"
            )

            return {
                "order_id": order.id,
                "order_number": order.order_number,
                "items_count": len(created_items),
                "first_check_date": first_check.isoformat(),
                "items": [
                    {
                        "id": it.id,
                        "name": it.name,
                        "quantity": it.quantity,
                        "unit": it.unit,
                    }
                    for it in created_items
                ],
            }

    async def confirm_order(self, order_id: int) -> bool:
        """Перевести заказ DRAFT → CONFIRMED."""
        from pds_ultimate.core.database import Order, OrderStatus

        with self._session_factory() as session:
            order = session.query(Order).filter(Order.id == order_id).first()
            if not order or order.status != OrderStatus.DRAFT:
                return False

            order.status = OrderStatus.CONFIRMED
            session.commit()
            logger.info(f"Order #{order.order_number} confirmed")
            return True

    # ═══════════════════════════════════════════════════════════════════════
    # Фаза 2: Финансовые шаги (income, expense, delivery)
    # ═══════════════════════════════════════════════════════════════════════

    async def set_income(
        self,
        order_id: int,
        amount: float,
        currency: str = "USD",
    ) -> dict:
        """Установить доход (сколько заплатили МНЕ)."""
        from pds_ultimate.core.database import (
            Order,
            Transaction,
            TransactionType,
        )

        with self._session_factory() as session:
            order = session.query(Order).filter(Order.id == order_id).first()
            if not order:
                return {"error": "Заказ не найден"}

            order.income = amount
            order.income_currency = currency

            # Запись транзакции
            tx = Transaction(
                order_id=order.id,
                transaction_type=TransactionType.INCOME,
                amount=amount,
                currency=currency,
                description=f"Доход по заказу #{order.order_number}",
                transaction_date=date.today(),
            )
            session.add(tx)
            session.commit()

            logger.info(
                f"Order #{order.order_number}: income set to "
                f"{amount} {currency}"
            )

            return {
                "order_number": order.order_number,
                "income": amount,
                "currency": currency,
            }

    async def set_expense(
        self,
        order_id: int,
        amount: float,
        currency: str = "USD",
    ) -> dict:
        """Установить расход на товар (сколько Я заплатил)."""
        from pds_ultimate.core.database import (
            Order,
            Transaction,
            TransactionType,
        )

        with self._session_factory() as session:
            order = session.query(Order).filter(Order.id == order_id).first()
            if not order:
                return {"error": "Заказ не найден"}

            order.expense_goods = amount
            order.expense_goods_currency = currency

            # Вычислить остаток (income - expense)
            remainder = None
            if order.income is not None:
                # Конвертация в одну валюту (USD) для расчёта
                income_usd = await self._to_usd(
                    order.income, order.income_currency or "USD"
                )
                expense_usd = await self._to_usd(amount, currency)
                remainder = income_usd - expense_usd

            tx = Transaction(
                order_id=order.id,
                transaction_type=TransactionType.EXPENSE_GOODS,
                amount=amount,
                currency=currency,
                description=f"Расход на товар по заказу #{order.order_number}",
                transaction_date=date.today(),
            )
            session.add(tx)
            session.commit()

            result = {
                "order_number": order.order_number,
                "expense_goods": amount,
                "currency": currency,
            }
            if remainder is not None:
                result["remainder_usd"] = round(remainder, 2)

            return result

    async def set_delivery_cost(
        self,
        order_id: int,
        amount: float,
        currency: str = "USD",
        delivery_type: str = "total",
        per_item_costs: Optional[list[dict]] = None,
    ) -> dict:
        """
        Установить стоимость доставки.
        delivery_type: "total" (общая сумма) или "per_item" (по позициям)
        per_item_costs: [{"item_id": 1, "cost": 50.0}, ...]
        """
        from pds_ultimate.core.database import (
            Order,
            OrderItem,
            Transaction,
            TransactionType,
        )

        with self._session_factory() as session:
            order = session.query(Order).filter(Order.id == order_id).first()
            if not order:
                return {"error": "Заказ не найден"}

            order.delivery_cost = amount
            order.delivery_currency = currency
            order.delivery_input_type = delivery_type

            if delivery_type == "per_item" and per_item_costs:
                for ic in per_item_costs:
                    item = session.query(OrderItem).filter(
                        OrderItem.id == ic["item_id"],
                        OrderItem.order_id == order.id,
                    ).first()
                    if item:
                        item.delivery_cost = ic["cost"]
            elif delivery_type == "total":
                # Пропорциональное распределение по цене или весу
                await self._distribute_delivery(session, order, amount)

            # Транзакция
            tx = Transaction(
                order_id=order.id,
                transaction_type=TransactionType.EXPENSE_DELIVERY,
                amount=amount,
                currency=currency,
                description=f"Доставка заказа #{order.order_number}",
                transaction_date=date.today(),
            )
            session.add(tx)
            session.commit()

            return {
                "order_number": order.order_number,
                "delivery_cost": amount,
                "currency": currency,
                "delivery_type": delivery_type,
            }

    # ═══════════════════════════════════════════════════════════════════════
    # Фаза 3: Закрытие заказа
    # ═══════════════════════════════════════════════════════════════════════

    async def finalize_order(self, order_id: int) -> dict:
        """
        Закрыть заказ: рассчитать чистую прибыль, распределить,
        записать в Master Finance.

        Формула:
          INCOME - EXPENSE_GOODS = REMAINDER
          REMAINDER - DELIVERY = NET_PROFIT
          NET_PROFIT → expense_percent% + savings_percent%
        """
        from pds_ultimate.core.database import (
            Order,
            OrderStatus,
            Transaction,
            TransactionType,
        )

        with self._session_factory() as session:
            order = session.query(Order).filter(Order.id == order_id).first()
            if not order:
                return {"error": "Заказ не найден"}

            # Проверки
            if order.income is None:
                return {"error": "Не указан доход"}
            if order.expense_goods is None:
                return {"error": "Не указан расход на товар"}

            # Конвертация в USD
            income_usd = await self._to_usd(
                order.income, order.income_currency or "USD"
            )
            expense_usd = await self._to_usd(
                order.expense_goods, order.expense_goods_currency or "USD"
            )
            delivery_usd = 0.0
            if order.delivery_cost:
                delivery_usd = await self._to_usd(
                    order.delivery_cost, order.delivery_currency or "USD"
                )

            # Расчёт
            remainder = income_usd - expense_usd
            net_profit = remainder - delivery_usd

            # Распределение
            exp_pct = config.finance.expense_percent
            sav_pct = config.finance.savings_percent

            to_expenses = round(net_profit * exp_pct / 100.0, 2)
            to_savings = round(net_profit * sav_pct / 100.0, 2)

            # Обновление заказа
            order.net_profit = round(net_profit, 2)
            order.profit_to_expenses = to_expenses
            order.profit_to_savings = to_savings
            order.expense_percent = exp_pct
            order.savings_percent = sav_pct
            order.status = OrderStatus.COMPLETED
            order.completed_date = date.today()

            # Транзакции распределения
            if to_expenses != 0:
                session.add(Transaction(
                    order_id=order.id,
                    transaction_type=TransactionType.PROFIT_EXPENSES,
                    amount=to_expenses,
                    currency="USD",
                    description=f"На расходы ({exp_pct}%) #{order.order_number}",
                    transaction_date=date.today(),
                ))

            if to_savings != 0:
                session.add(Transaction(
                    order_id=order.id,
                    transaction_type=TransactionType.PROFIT_SAVINGS,
                    amount=to_savings,
                    currency="USD",
                    description=f"Отложения ({sav_pct}%) #{order.order_number}",
                    transaction_date=date.today(),
                ))

            session.commit()

            logger.info(
                f"Order #{order.order_number} finalized: "
                f"income={income_usd}, expense={expense_usd}, "
                f"delivery={delivery_usd}, net_profit={net_profit}"
            )

            return {
                "order_number": order.order_number,
                "income_usd": round(income_usd, 2),
                "expense_goods_usd": round(expense_usd, 2),
                "remainder_usd": round(remainder, 2),
                "delivery_usd": round(delivery_usd, 2),
                "net_profit_usd": round(net_profit, 2),
                "to_expenses": to_expenses,
                "to_savings": to_savings,
                "expense_percent": exp_pct,
                "savings_percent": sav_pct,
            }

    # ═══════════════════════════════════════════════════════════════════════
    # Запросы
    # ═══════════════════════════════════════════════════════════════════════

    async def get_active_orders(self) -> list[dict]:
        """Все активные заказы (не архивные)."""
        from pds_ultimate.core.database import Order, OrderStatus

        with self._session_factory() as session:
            orders = (
                session.query(Order)
                .filter(Order.status.notin_([
                    OrderStatus.COMPLETED, OrderStatus.ARCHIVED,
                ]))
                .order_by(Order.created_at.desc())
                .all()
            )

            return [self._order_to_dict(o) for o in orders]

    async def get_order_by_id(self, order_id: int) -> Optional[dict]:
        """Получить заказ по ID."""
        from pds_ultimate.core.database import Order

        with self._session_factory() as session:
            order = session.query(Order).filter(Order.id == order_id).first()
            if not order:
                return None
            return self._order_to_dict(order, include_items=True)

    async def get_order_by_number(self, order_number: str) -> Optional[dict]:
        """Получить заказ по номеру."""
        from pds_ultimate.core.database import Order

        with self._session_factory() as session:
            order = (
                session.query(Order)
                .filter(Order.order_number == order_number)
                .first()
            )
            if not order:
                return None
            return self._order_to_dict(order, include_items=True)

    async def search_orders(self, query: str) -> list[dict]:
        """Поиск заказов по тексту (номер, описание, контрагент)."""
        from pds_ultimate.core.database import Order, OrderItem

        with self._session_factory() as session:
            orders = (
                session.query(Order)
                .outerjoin(OrderItem)
                .filter(
                    Order.order_number.ilike(f"%{query}%")
                    | Order.description.ilike(f"%{query}%")
                    | Order.notes.ilike(f"%{query}%")
                    | OrderItem.name.ilike(f"%{query}%")
                )
                .distinct()
                .all()
            )

            return [self._order_to_dict(o) for o in orders]

    # ═══════════════════════════════════════════════════════════════════════
    # Форматирование
    # ═══════════════════════════════════════════════════════════════════════

    def format_order(self, order_data: dict) -> str:
        """Человекочитаемый формат заказа."""
        lines = [f"📦 Заказ #{order_data['order_number']}"]
        lines.append(f"Статус: {order_data['status']}")

        if order_data.get("supplier"):
            lines.append(f"Поставщик: {order_data['supplier']}")

        if order_data.get("income") is not None:
            lines.append(
                f"💰 Доход: {order_data['income']} "
                f"{order_data.get('income_currency', 'USD')}"
            )

        if order_data.get("expense_goods") is not None:
            lines.append(
                f"💸 Расход: {order_data['expense_goods']} "
                f"{order_data.get('expense_goods_currency', 'USD')}"
            )

        if order_data.get("delivery_cost") is not None:
            lines.append(
                f"🚚 Доставка: {order_data['delivery_cost']} "
                f"{order_data.get('delivery_currency', 'USD')}"
            )

        if order_data.get("net_profit") is not None:
            lines.append(f"📊 Чистая прибыль: ${order_data['net_profit']}")

        # Позиции
        items = order_data.get("items", [])
        if items:
            lines.append(f"\n📋 Позиции ({len(items)}):")
            for i, item in enumerate(items, 1):
                status_emoji = {
                    "pending": "⏳",
                    "shipped": "🚢",
                    "arrived": "✅",
                    "cancelled": "❌",
                }.get(item.get("status", ""), "❓")

                line = (
                    f"  {i}. {status_emoji} {item['name']} — "
                    f"{item['quantity']} {item.get('unit', 'шт')}"
                )

                if item.get("tracking_number"):
                    line += f" | Трек: {item['tracking_number']}"

                lines.append(line)

        return "\n".join(lines)

    def format_orders_list(self, orders: list[dict]) -> str:
        """Форматирование списка заказов."""
        if not orders:
            return "📦 Активных заказов нет."

        lines = [f"📦 Активные заказы ({len(orders)}):\n"]
        for o in orders:
            items_count = len(o.get("items", []))
            status = o.get("status", "?")
            lines.append(
                f"• #{o['order_number']} | {status} | "
                f"{items_count} поз."
                + (f" | {o.get('description', '')[:40]}" if o.get("description") else "")
            )

        return "\n".join(lines)

    # ═══════════════════════════════════════════════════════════════════════
    # Internal helpers
    # ═══════════════════════════════════════════════════════════════════════

    async def _generate_order_number(self, session) -> str:
        """Генерация уникального номера заказа: PDS-YYYYMMDD-NNN."""
        from pds_ultimate.core.database import Order

        today = date.today()
        prefix = f"PDS-{today.strftime('%Y%m%d')}"

        # Найти последний номер за сегодня
        last = (
            session.query(Order)
            .filter(Order.order_number.like(f"{prefix}%"))
            .order_by(Order.order_number.desc())
            .first()
        )

        if last:
            try:
                last_num = int(last.order_number.split("-")[-1])
                next_num = last_num + 1
            except (ValueError, IndexError):
                next_num = 1
        else:
            next_num = 1

        return f"{prefix}-{next_num:03d}"

    async def _find_or_create_contact(
        self,
        session,
        name: str,
        contact_type,
    ) -> int:
        """Найти контакт по имени или создать новый."""
        from pds_ultimate.core.database import Contact

        contact = (
            session.query(Contact)
            .filter(Contact.name.ilike(name))
            .first()
        )

        if contact:
            return contact.id

        contact = Contact(name=name, contact_type=contact_type)
        session.add(contact)
        session.flush()
        return contact.id

    async def _distribute_delivery(
        self,
        session,
        order,
        total_delivery: float,
    ) -> None:
        """
        Пропорциональное распределение общей доставки по позициям.
        Приоритет: по весу → по цене → поровну.
        """
        from pds_ultimate.core.database import OrderItem

        items = (
            session.query(OrderItem)
            .filter(OrderItem.order_id == order.id)
            .all()
        )

        if not items:
            return

        # Попытка распределить по весу
        total_weight = sum(it.weight or 0 for it in items)
        if total_weight > 0:
            for it in items:
                share = (it.weight or 0) / total_weight
                it.delivery_cost = round(total_delivery * share, 2)
            return

        # По цене
        total_value = sum(
            (it.unit_price or 0) * it.quantity for it in items
        )
        if total_value > 0:
            for it in items:
                val = (it.unit_price or 0) * it.quantity
                share = val / total_value
                it.delivery_cost = round(total_delivery * share, 2)
            return

        # Поровну
        per_item = round(total_delivery / len(items), 2)
        for it in items:
            it.delivery_cost = per_item

    async def _to_usd(self, amount: float, currency: str) -> float:
        """Конвертация в USD."""
        if currency == "USD":
            return amount

        from pds_ultimate.core.database import CurrencyRate

        with self._session_factory() as session:
            rate_record = (
                session.query(CurrencyRate)
                .filter(
                    CurrencyRate.base_currency == "USD",
                    CurrencyRate.target_currency == currency,
                )
                .order_by(CurrencyRate.rate_date.desc())
                .first()
            )

            if rate_record and rate_record.rate > 0:
                # rate = сколько единиц target за 1 USD
                # значит amount target / rate = USD
                return amount / rate_record.rate

        # Фиксированные курсы из конфига как fallback
        fixed = config.currency.fixed_rates.get(currency)
        if fixed and fixed > 0:
            return amount / fixed

        logger.warning(f"No rate found for {currency}/USD, returning as-is")
        return amount

    def _order_to_dict(
        self,
        order,
        include_items: bool = False,
    ) -> dict:
        """Преобразовать ORM объект Order в dict."""
        d = {
            "id": order.id,
            "order_number": order.order_number,
            "status": order.status.value,
            "income": order.income,
            "income_currency": order.income_currency,
            "expense_goods": order.expense_goods,
            "expense_goods_currency": order.expense_goods_currency,
            "delivery_cost": order.delivery_cost,
            "delivery_currency": order.delivery_currency,
            "net_profit": order.net_profit,
            "description": order.description,
            "order_date": order.order_date.isoformat() if order.order_date else None,
            "completed_date": (
                order.completed_date.isoformat() if order.completed_date else None
            ),
        }

        # Контрагенты
        if order.supplier:
            d["supplier"] = order.supplier.name
        if order.client:
            d["client"] = order.client.name

        # Позиции
        if include_items or True:
            d["items"] = [
                {
                    "id": it.id,
                    "name": it.name,
                    "quantity": it.quantity,
                    "unit": it.unit,
                    "unit_price": it.unit_price,
                    "status": it.status.value,
                    "tracking_number": it.tracking_number,
                    "arrival_date": (
                        it.arrival_date.isoformat() if it.arrival_date else None
                    ),
                    "delivery_cost": it.delivery_cost,
                    "next_check_date": (
                        it.next_check_date.isoformat()
                        if it.next_check_date else None
                    ),
                }
                for it in order.items
            ]

        return d
