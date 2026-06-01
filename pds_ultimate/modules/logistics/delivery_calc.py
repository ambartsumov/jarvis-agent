"""
PDS-Ultimate Delivery Calculator
====================================
Расчёт стоимости доставки.

По ТЗ:
- Когда все позиции «Прибыло» → «Доставку по каждой позиции или общей суммой?»
- Если общей → распределение пропорционально (по весу или цене)
"""

from __future__ import annotations


class DeliveryCalculator:
    """
    Калькулятор доставки с пропорциональным распределением.
    """

    def __init__(self, db_session_factory):
        self._session_factory = db_session_factory

    async def calculate_total_delivery(
        self,
        order_id: int,
        total_cost: float,
        currency: str = "USD",
    ) -> dict:
        """
        Распределить общую стоимость доставки по позициям заказа.
        Приоритет: по весу → по цене → поровну.
        """
        from pds_ultimate.core.database import OrderItem

        with self._session_factory() as session:
            items = (
                session.query(OrderItem)
                .filter(OrderItem.order_id == order_id)
                .all()
            )

            if not items:
                return {"error": "Позиции не найдены"}

            distribution = self._distribute(items, total_cost)

            for it in items:
                share = distribution.get(it.id, 0.0)
                it.delivery_cost = share

            session.commit()

            return {
                "order_id": order_id,
                "total_delivery": total_cost,
                "currency": currency,
                "method": distribution.get("_method", "equal"),
                "items": [
                    {
                        "item_id": it.id,
                        "name": it.name,
                        "delivery_share": distribution.get(it.id, 0.0),
                    }
                    for it in items
                ],
            }

    async def set_per_item_delivery(
        self,
        order_id: int,
        item_costs: list[dict],
    ) -> dict:
        """
        Установить стоимость доставки для каждой позиции отдельно.
        item_costs: [{"item_id": 1, "cost": 50.0}, ...]
        """
        from pds_ultimate.core.database import OrderItem

        with self._session_factory() as session:
            total = 0.0
            updated = []

            for ic in item_costs:
                item = session.query(OrderItem).filter(
                    OrderItem.id == ic["item_id"],
                    OrderItem.order_id == order_id,
                ).first()

                if item:
                    cost = float(ic["cost"])
                    item.delivery_cost = cost
                    total += cost
                    updated.append({
                        "item_id": item.id,
                        "name": item.name,
                        "delivery_cost": cost,
                    })

            session.commit()

            return {
                "order_id": order_id,
                "total_delivery": round(total, 2),
                "items": updated,
            }

    async def get_delivery_summary(self, order_id: int) -> dict:
        """Получить сводку по доставке заказа."""
        from pds_ultimate.core.database import Order, OrderItem

        with self._session_factory() as session:
            order = session.query(Order).filter(Order.id == order_id).first()
            if not order:
                return {"error": "Заказ не найден"}

            items = (
                session.query(OrderItem)
                .filter(OrderItem.order_id == order_id)
                .all()
            )

            items_data = []
            total_per_item = 0.0

            for it in items:
                cost = it.delivery_cost or 0.0
                total_per_item += cost
                items_data.append({
                    "name": it.name,
                    "delivery_cost": cost,
                    "total_cost": it.total_cost,
                })

            return {
                "order_number": order.order_number,
                "order_delivery_cost": order.delivery_cost,
                "sum_per_item": round(total_per_item, 2),
                "delivery_type": order.delivery_input_type,
                "items": items_data,
            }

    def format_delivery_question(self, order_data: dict) -> str:
        """Сформировать вопрос о способе ввода доставки."""
        items = order_data.get("items", [])
        lines = [
            "🚚 Все позиции прибыли! Введите стоимость доставки.\n",
            "Как ввести?",
            "1️⃣ Общей суммой (распределю пропорционально)",
            "2️⃣ По каждой позиции отдельно\n",
            "📋 Позиции:",
        ]

        for i, it in enumerate(items, 1):
            lines.append(
                f"  {i}. {it['name']} — "
                f"{it.get('quantity', '?')} {it.get('unit', 'шт')}"
            )

        return "\n".join(lines)

    # ═══════════════════════════════════════════════════════════════════════
    # Internal
    # ═══════════════════════════════════════════════════════════════════════

    def _distribute(
        self,
        items: list,
        total: float,
    ) -> dict:
        """
        Распределить сумму по позициям.
        Приоритет: по весу → по цене → поровну.
        """
        result = {}

        # По весу
        total_weight = sum(it.weight or 0 for it in items)
        if total_weight > 0:
            for it in items:
                share = ((it.weight or 0) / total_weight) * total
                result[it.id] = round(share, 2)
            result["_method"] = "weight"
            return result

        # По цене
        total_value = sum((it.unit_price or 0) * it.quantity for it in items)
        if total_value > 0:
            for it in items:
                val = (it.unit_price or 0) * it.quantity
                share = (val / total_value) * total
                result[it.id] = round(share, 2)
            result["_method"] = "price"
            return result

        # Поровну
        per_item = round(total / len(items), 2)
        for it in items:
            result[it.id] = per_item
        result["_method"] = "equal"

        return result
