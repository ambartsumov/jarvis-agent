"""
PDS-Ultimate Logistics Tools
=============================
Инструменты для логистики и заказов.

ФУНКЦИИ:
- Создание заказов из текста
- Статусы заказов
- Трек-номера
- Поиск и архивация
- Anti-forget проверка
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any, Optional

from pds_ultimate.config import config, logger
from pds_ultimate.core.tools import Tool, ToolParameter, ToolResult, ToolRegistry

# ─── Logistics Tools ─────────────────────────────────────────────────────────


async def tool_create_order(
    items_text: str,
    db_session: Any = None,
) -> ToolResult:
    """
    Создать новый заказ из текстового описания позиций.
    
    Пример:
    "100 балаклав, 50 футболок, 25 курток"
    """
    if not db_session:
        return ToolResult("create_order", False, "", error="Нет сессии БД")
    
    try:
        # Parse items (LLM-based)
        from pds_ultimate.core.llm_engine import llm_engine
        parsed = await llm_engine.parse_order(items_text)
        
        if not parsed:
            return ToolResult(
                "create_order", False, "",
                error="Не удалось распознать позиции"
            )
        
        # Create order
        from pds_ultimate.core.database import Order, OrderItem, OrderStatus, ItemStatus
        
        order_count = db_session.query(Order).count()
        order_number = f"ORD-{order_count + 1:04d}"
        
        order = Order(
            order_number=order_number,
            status=OrderStatus.CONFIRMED,
            order_date=date.today(),
        )
        db_session.add(order)
        db_session.flush()
        
        # Add items
        created_items = []
        for item_data in parsed:
            first_check = date.today() + timedelta(
                days=config.logistics.first_status_check_days
            )
            item = OrderItem(
                order_id=order.id,
                name=item_data.get("name", "?"),
                quantity=float(item_data.get("quantity", 1)),
                unit=item_data.get("unit", "шт"),
                unit_price=item_data.get("unit_price"),
                price_currency=item_data.get("currency", "USD"),
                status=ItemStatus.PENDING,
                next_check_date=first_check,
            )
            db_session.add(item)
            created_items.append(item_data)
        
        db_session.commit()
        
        # Format result
        items_list = "\n".join(
            f"  {i + 1}. {it.get('name', '?')} — {it.get('quantity', '?')} {it.get('unit', 'шт')}"
            for i, it in enumerate(created_items)
        )
        
        return ToolResult(
            "create_order",
            True,
            f"✅ Заказ {order_number} создан ({len(created_items)} позиций):\n{items_list}",
            data={
                "order_id": order.id,
                "order_number": order_number,
                "items_count": len(created_items),
            },
        )
        
    except Exception as e:
        logger.error(f"tool_create_order failed: {e}")
        return ToolResult("create_order", False, "", error=str(e))


async def tool_get_orders_status(
    order_number: Optional[str] = None,
    db_session: Any = None,
) -> ToolResult:
    """Получить статус заказа по номеру или всех активных."""
    if not db_session:
        return ToolResult("get_orders_status", False, "", error="Нет сессии БД")
    
    try:
        from pds_ultimate.core.database import Order, OrderItem, OrderStatus
        
        query = db_session.query(Order)
        
        if order_number:
            query = query.filter(Order.order_number == order_number)
        else:
            query = query.filter(Order.status.in_([
                OrderStatus.CONFIRMED,
                OrderStatus.IN_PRODUCTION,
                OrderStatus.SHIPPED,
            ]))
        
        orders = query.all()
        
        if not orders:
            return ToolResult(
                "get_orders_status",
                False,
                order_number
                if order_number
                else "Нет активных заказов"
            )
        
        result_lines = []
        for order in orders:
            items_count = db_session.query(OrderItem).filter(
                OrderItem.order_id == order.id
            ).count()
            
            result_lines.append(
                f"📦 {order.order_number}: {order.status.value} "
                f"({items_count} поз., {order.order_date})"
            )
        
        return ToolResult(
            "get_orders_status",
            True,
            "\n".join(result_lines),
            data={"orders": [{"id": o.id, "number": o.order_number, "status": o.status.value} for o in orders]},
        )
        
    except Exception as e:
        logger.error(f"tool_get_orders_status failed: {e}")
        return ToolResult("get_orders_status", False, "", error=str(e))


async def tool_update_order_status(
    order_number: str,
    new_status: str,
    db_session: Any = None,
) -> ToolResult:
    """Обновить статус заказа."""
    if not db_session:
        return ToolResult("update_order_status", False, "", error="Нет сессии БД")
    
    try:
        from pds_ultimate.core.database import Order, OrderStatus
        
        # Map status string to enum
        status_map = {
            "confirmed": OrderStatus.CONFIRMED,
            "production": OrderStatus.IN_PRODUCTION,
            "shipped": OrderStatus.SHIPPED,
            "delivered": OrderStatus.DELIVERED,
            "cancelled": OrderStatus.CANCELLED,
        }
        
        new_status_enum = status_map.get(new_status.lower())
        if not new_status_enum:
            return ToolResult(
                "update_order_status",
                False,
                f"Неизвестный статус: {new_status}. Доступные: {list(status_map.keys())}"
            )
        
        order = db_session.query(Order).filter(
            Order.order_number == order_number
        ).first()
        
        if not order:
            return ToolResult(
                "update_order_status",
                False,
                f"Заказ {order_number} не найден"
            )
        
        old_status = order.status
        order.status = new_status_enum
        db_session.commit()
        
        return ToolResult(
            "update_order_status",
            True,
            f"✅ Заказ {order_number}: {old_status.value} → {new_status_enum.value}",
            data={
                "order_id": order.id,
                "old_status": old_status.value,
                "new_status": new_status_enum.value,
            },
        )
        
    except Exception as e:
        logger.error(f"tool_update_order_status failed: {e}")
        return ToolResult("update_order_status", False, "", error=str(e))


async def tool_add_tracking(
    order_number: str,
    tracking_number: str,
    db_session: Any = None,
) -> ToolResult:
    """Добавить трек-номер к заказу."""
    if not db_session:
        return ToolResult("add_tracking", False, "", error="Нет сессии БД")
    
    try:
        from pds_ultimate.core.database import Order
        
        order = db_session.query(Order).filter(
            Order.order_number == order_number
        ).first()
        
        if not order:
            return ToolResult(
                "add_tracking",
                False,
                f"Заказ {order_number} не найден"
            )
        
        order.tracking_number = tracking_number
        order.status = OrderStatus.SHIPPED
        db_session.commit()
        
        return ToolResult(
            "add_tracking",
            True,
            f"✅ Трек-номер {tracking_number} добавлен к заказу {order_number}",
            data={
                "order_id": order.id,
                "tracking_number": tracking_number,
            },
        )
        
    except Exception as e:
        logger.error(f"tool_add_tracking failed: {e}")
        return ToolResult("add_tracking", False, "", error=str(e))


async def tool_search_orders(
    query: str,
    db_session: Any = None,
) -> ToolResult:
    """Поиск заказов по запросу."""
    if not db_session:
        return ToolResult("search_orders", False, "", error="Нет сессии БД")
    
    try:
        from pds_ultimate.core.database import Order, OrderItem
        
        # Simple search by order number or item name
        orders = db_session.query(Order).limit(20).all()
        
        # Filter by query
        results = []
        for order in orders:
            if query.lower() in order.order_number.lower():
                results.append(order)
                continue
            
            # Search items
            items = db_session.query(OrderItem).filter(
                OrderItem.order_id == order.id
            ).all()
            
            for item in items:
                if query.lower() in item.name.lower():
                    results.append(order)
                    break
        
        if not results:
            return ToolResult(
                "search_orders",
                False,
                f"Заказы по запросу '{query}' не найдены"
            )
        
        result_lines = [
            f"📦 {o.order_number}: {o.status.value} ({o.order_date})"
            for o in results[:10]
        ]
        
        return ToolResult(
            "search_orders",
            True,
            f"Найдено заказов: {len(results)}\n" + "\n".join(result_lines),
            data={"orders": [{"id": o.id, "number": o.order_number} for o in results]},
        )
        
    except Exception as e:
        logger.error(f"tool_search_orders failed: {e}")
        return ToolResult("search_orders", False, "", error=str(e))


async def tool_archive_order(
    order_number: str,
    db_session: Any = None,
) -> ToolResult:
    """Архивировать заказ."""
    if not db_session:
        return ToolResult("archive_order", False, "", error="Нет сессии БД")
    
    try:
        from pds_ultimate.core.database import Order, OrderStatus
        
        order = db_session.query(Order).filter(
            Order.order_number == order_number
        ).first()
        
        if not order:
            return ToolResult(
                "archive_order",
                False,
                f"Заказ {order_number} не найден"
            )
        
        if order.status != OrderStatus.DELIVERED:
            return ToolResult(
                "archive_order",
                False,
                "Можно архивировать только доставленные заказы"
            )
        
        order.is_archived = True
        db_session.commit()
        
        return ToolResult(
            "archive_order",
            True,
            f"✅ Заказ {order_number} заархивирован",
            data={"order_id": order.id},
        )
        
    except Exception as e:
        logger.error(f"tool_archive_order failed: {e}")
        return ToolResult("archive_order", False, "", error=str(e))


async def tool_get_order_history(
    days: int = 30,
    db_session: Any = None,
) -> ToolResult:
    """Получить историю заказов за период."""
    if not db_session:
        return ToolResult("get_order_history", False, "", error="Нет сессии БД")
    
    try:
        from pds_ultimate.core.database import Order
        
        from_date = date.today() - timedelta(days=days)
        
        orders = db_session.query(Order).filter(
            Order.order_date >= from_date
        ).order_by(Order.order_date.desc()).limit(50).all()
        
        if not orders:
            return ToolResult(
                "get_order_history",
                False,
                f"Нет заказов за последние {days} дней"
            )
        
        result_lines = [
            f"📦 {o.order_number}: {o.status.value} ({o.order_date})"
            for o in orders[:20]
        ]
        
        return ToolResult(
            "get_order_history",
            True,
            f"Заказы за {days} дней ({len(orders)}):\n" + "\n".join(result_lines),
            data={
                "orders": [
                    {"id": o.id, "number": o.order_number, "status": o.status.value, "date": str(o.order_date)}
                    for o in orders
                ]
            },
        )
        
    except Exception as e:
        logger.error(f"tool_get_order_history failed: {e}")
        return ToolResult("get_order_history", False, "", error=str(e))


async def tool_anti_forget_check(
    db_session: Any = None,
) -> ToolResult:
    """Anti-forget: проверка забытых заказов."""
    if not db_session:
        return ToolResult("anti_forget_check", False, "", error="Нет сессии БД")
    
    try:
        from pds_ultimate.core.database import Order, OrderStatus
        
        # Find orders that need status check
        cutoff_date = date.today() - timedelta(
            days=config.logistics.first_status_check_days
        )
        
        orders = db_session.query(Order).filter(
            Order.status.in_([OrderStatus.CONFIRMED, OrderStatus.IN_PRODUCTION]),
            Order.order_date <= cutoff_date,
        ).all()
        
        if not orders:
            return ToolResult(
                "anti_forget_check",
                True,
                "✅ Все заказы в порядке, забытых нет"
            )
        
        result_lines = [
            f"⚠️ {o.order_number}: {o.status.value} ({o.order_date})"
            for o in orders[:10]
        ]
        
        return ToolResult(
            "anti_forget_check",
            True,
            f"⚠️ Найдено забытых заказов: {len(orders)}\n" + "\n".join(result_lines),
            data={
                "forgotten_orders": [
                    {"id": o.id, "number": o.order_number, "status": o.status.value}
                    for o in orders
                ]
            },
        )
        
    except Exception as e:
        logger.error(f"tool_anti_forget_check failed: {e}")
        return ToolResult("anti_forget_check", False, "", error=str(e))


# ─── Tool Registration ───────────────────────────────────────────────────────

def register_logistics_tools(registry: ToolRegistry) -> None:
    """Зарегистрировать logistics инструменты."""
    
    registry.register(
        Tool(
            name="create_order",
            description="Создать новый заказ из текстового описания позиций",
            parameters=[
                ToolParameter(
                    "items_text", "string",
                    "Текст с позициями (например: '100 балаклав, 50 футболок')"
                ),
            ],
            handler=tool_create_order,
            category="logistics",
        )
    )
    
    registry.register(
        Tool(
            name="get_orders_status",
            description="Получить статус заказа по номеру или всех активных",
            parameters=[
                ToolParameter(
                    "order_number", "string",
                    "Номер заказа (необязательно, если нет — все активные)",
                    required=False,
                ),
            ],
            handler=tool_get_orders_status,
            category="logistics",
        )
    )
    
    registry.register(
        Tool(
            name="update_order_status",
            description="Обновить статус заказа",
            parameters=[
                ToolParameter("order_number", "string", "Номер заказа"),
                ToolParameter(
                    "new_status", "string",
                    "Новый статус (confirmed, production, shipped, delivered, cancelled)",
                ),
            ],
            handler=tool_update_order_status,
            category="logistics",
        )
    )
    
    registry.register(
        Tool(
            name="add_tracking",
            description="Добавить трек-номер к заказу",
            parameters=[
                ToolParameter("order_number", "string", "Номер заказа"),
                ToolParameter("tracking_number", "string", "Трек-номер"),
            ],
            handler=tool_add_tracking,
            category="logistics",
        )
    )
    
    registry.register(
        Tool(
            name="search_orders",
            description="Поиск заказов по запросу",
            parameters=[
                ToolParameter("query", "string", "Поисковый запрос"),
            ],
            handler=tool_search_orders,
            category="logistics",
        )
    )
    
    registry.register(
        Tool(
            name="archive_order",
            description="Архивировать доставленный заказ",
            parameters=[
                ToolParameter("order_number", "string", "Номер заказа"),
            ],
            handler=tool_archive_order,
            category="logistics",
        )
    )
    
    registry.register(
        Tool(
            name="get_order_history",
            description="Получить историю заказов за период",
            parameters=[
                ToolParameter(
                    "days", "number",
                    "Период в днях (по умолчанию 30)",
                    required=False,
                    default=30,
                ),
            ],
            handler=tool_get_order_history,
            category="logistics",
        )
    )
    
    registry.register(
        Tool(
            name="anti_forget_check",
            description="Anti-forget: проверка забытых заказов",
            parameters=[],
            handler=tool_anti_forget_check,
            category="logistics",
        )
    )


__all__ = [
    "tool_create_order",
    "tool_get_orders_status",
    "tool_update_order_status",
    "tool_add_tracking",
    "tool_search_orders",
    "tool_archive_order",
    "tool_get_order_history",
    "tool_anti_forget_check",
    "register_logistics_tools",
]
