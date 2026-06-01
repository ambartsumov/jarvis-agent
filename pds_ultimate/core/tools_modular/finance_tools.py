"""
PDS-Ultimate Finance Tools
===========================
Инструменты для финансов и учёта прибыли.

ФУНКЦИИ:
- Доходы (income)
- Расходы (expense)
- Стоимость доставки
- Отчёт о прибыли (INCOME - GOODS = REMAINDER - DELIVERY = NET_PROFIT)
- Конвертация валют (USD/TMT/CNY)
- Финансовая сводка
- Экспорт в Excel

ARCHITECTURE:
- Чистые функции с явными зависимостями
- Error handling с подробными сообщениями
- Type hints для всех параметров
- Logging всех операций
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from pds_ultimate.config import config, logger
from pds_ultimate.core.tools import Tool, ToolParameter, ToolResult, ToolRegistry

# ─── Constants ───────────────────────────────────────────────────────────────

# Фиксированные курсы по ТЗ
FIXED_RATES = {
    "USD_TMT": 19.5,
    "USD_CNY": 7.1,
    "TMT_USD": 1 / 19.5,
    "CNY_USD": 1 / 7.1,
}

# ─── Finance Tools ──────────────────────────────────────────────────────────


async def tool_set_income(
    amount: float,
    currency: str = "USD",
    description: str = "",
    db_session: Any = None,
) -> ToolResult:
    """
    Записать доход.
    
    Формула: ДОХОД (сколько заплатили МНЕ)
    """
    if not db_session:
        return ToolResult("set_income", False, "", error="Нет сессии БД")
    
    if amount <= 0:
        return ToolResult("set_income", False, "", error="Сумма должна быть > 0")
    
    try:
        from pds_ultimate.core.database import FinancialRecord, RecordType
        
        record = FinancialRecord(
            record_type=RecordType.INCOME,
            amount=amount,
            currency=currency.upper(),
            description=description[:500],
            record_date=date.today(),
        )
        db_session.add(record)
        db_session.commit()
        
        return ToolResult(
            "set_income",
            True,
            f"✅ Доход: {amount:,.2f} {currency.upper()} записан",
            data={"record_id": record.id, "amount": amount, "currency": currency},
        )
        
    except Exception as e:
        logger.error(f"tool_set_income failed: {e}")
        return ToolResult("set_income", False, "", error=str(e))


async def tool_set_expense(
    amount: float,
    currency: str = "USD",
    description: str = "",
    category: str = "goods",
    db_session: Any = None,
) -> ToolResult:
    """
    Записать расход.
    
    Формула: РАСХОД_ТОВАР (сколько Я заплатил поставщику)
    """
    if not db_session:
        return ToolResult("set_expense", False, "", error="Нет сессии БД")
    
    if amount <= 0:
        return ToolResult("set_expense", False, "", error="Сумма должна быть > 0")
    
    try:
        from pds_ultimate.core.database import FinancialRecord, RecordType
        
        record = FinancialRecord(
            record_type=RecordType.EXPENSE,
            amount=amount,
            currency=currency.upper(),
            description=description[:500],
            category=category,
            record_date=date.today(),
        )
        db_session.add(record)
        db_session.commit()
        
        return ToolResult(
            "set_expense",
            True,
            f"✅ Расход: {amount:,.2f} {currency.upper()} ({category}) записан",
            data={"record_id": record.id, "amount": amount, "category": category},
        )
        
    except Exception as e:
        logger.error(f"tool_set_expense failed: {e}")
        return ToolResult("set_expense", False, "", error=str(e))


async def tool_set_delivery_cost(
    amount: float,
    currency: str = "USD",
    order_number: Optional[str] = None,
    db_session: Any = None,
) -> ToolResult:
    """
    Записать стоимость доставки.
    
    Формула: РАСХОД_ДОСТАВКА (вычитается из ОСТАТКА)
    """
    if not db_session:
        return ToolResult("set_delivery_cost", False, "", error="Нет сессии БД")
    
    if amount <= 0:
        return ToolResult("set_delivery_cost", False, "", error="Сумма должна быть > 0")
    
    try:
        from pds_ultimate.core.database import FinancialRecord, RecordType
        
        description = f"Доставка" + (f" для {order_number}" if order_number else "")
        
        record = FinancialRecord(
            record_type=RecordType.EXPENSE,
            amount=amount,
            currency=currency.upper(),
            description=description,
            category="delivery",
            record_date=date.today(),
        )
        db_session.add(record)
        db_session.commit()
        
        return ToolResult(
            "set_delivery_cost",
            True,
            f"✅ Доставка: {amount:,.2f} {currency.upper()}" + (f" ({order_number})" if order_number else ""),
            data={"record_id": record.id, "amount": amount, "order": order_number},
        )
        
    except Exception as e:
        logger.error(f"tool_set_delivery_cost failed: {e}")
        return ToolResult("set_delivery_cost", False, "", error=str(e))


async def tool_get_profit_report(
    days: int = 30,
    db_session: Any = None,
) -> ToolResult:
    """
    Отчёт о прибыли по формуле:
    INCOME - GOODS = REMAINDER - DELIVERY = NET_PROFIT
    """
    if not db_session:
        return ToolResult("get_profit_report", False, "", error="Нет сессии БД")
    
    try:
        from pds_ultimate.core.database import FinancialRecord, RecordType
        
        from_date = date.today() - timedelta(days=days)
        
        # Get records
        records = db_session.query(FinancialRecord).filter(
            FinancialRecord.record_date >= from_date
        ).all()
        
        # Calculate by category
        income = 0.0
        goods_expense = 0.0
        delivery_expense = 0.0
        other_expense = 0.0
        
        for record in records:
            if record.record_type == RecordType.INCOME:
                income += record.amount
            elif record.record_type == RecordType.EXPENSE:
                if record.category == "goods":
                    goods_expense += record.amount
                elif record.category == "delivery":
                    delivery_expense += record.amount
                else:
                    other_expense += record.amount
        
        # Formula: INCOME - GOODS = REMAINDER - DELIVERY = NET_PROFIT
        remainder = income - goods_expense
        net_profit = remainder - delivery_expense - other_expense
        
        # Distribution (by config)
        expense_amount = net_profit * (config.finance.expense_percent / 100)
        savings_amount = net_profit * (config.finance.savings_percent / 100)
        
        report = f"""
💰 ОТЧЁТ О ПРИБЫЛИ ({days} дней)
═══════════════════════════════

📥 ДОХОД: {income:,.2f} USD
📤 РАСХОД ТОВАР: {goods_expense:,.2f} USD
───────────────────────────
💵 ОСТАТОК: {remainder:,.2f} USD

📤 РАСХОД ДОСТАВКА: {delivery_expense:,.2f} USD
📤 РАСХОД ПРОЧЕЕ: {other_expense:,.2f} USD
───────────────────────────
✅ ЧИСТАЯ ПРИБЫЛЬ: {net_profit:,.2f} USD

Распределение:
  • На расходы ({config.finance.expense_percent}%): {expense_amount:,.2f} USD
  • На отложения ({config.finance.savings_percent}%): {savings_amount:,.2f} USD
"""
        
        return ToolResult(
            "get_profit_report",
            True,
            report,
            data={
                "income": income,
                "goods_expense": goods_expense,
                "delivery_expense": delivery_expense,
                "other_expense": other_expense,
                "remainder": remainder,
                "net_profit": net_profit,
                "expense_amount": expense_amount,
                "savings_amount": savings_amount,
            },
        )
        
    except Exception as e:
        logger.error(f"tool_get_profit_report failed: {e}")
        return ToolResult("get_profit_report", False, "", error=str(e))


async def tool_convert_currency(
    amount: float,
    from_currency: str,
    to_currency: str,
) -> ToolResult:
    """
    Конвертация валют.
    
    Фиксированные курсы:
    - 1 USD = 19.5 TMT
    - 1 USD = 7.1 CNY
    """
    from_curr = from_currency.upper()
    to_curr = to_currency.upper()
    
    # Same currency
    if from_curr == to_curr:
        return ToolResult(
            "convert_currency",
            True,
            f"{amount:,.2f} {from_curr} = {amount:,.2f} {to_curr}",
            data={"result": amount, "rate": 1.0},
        )
    
    # Try fixed rates
    rate_key = f"{from_curr}_{to_curr}"
    if rate_key in FIXED_RATES:
        rate = FIXED_RATES[rate_key]
        result = amount * rate
        return ToolResult(
            "convert_currency",
            True,
            f"{amount:,.2f} {from_curr} = {result:,.2f} {to_curr}\n"
            f"Курс: 1 {from_curr} = {rate} {to_curr}",
            data={"result": result, "rate": rate},
        )
    
    # Try via USD
    usd_key_from = f"{from_curr}_USD"
    usd_key_to = f"USD_{to_curr}"
    
    if usd_key_from in FIXED_RATES and usd_key_to in FIXED_RATES:
        rate_from = FIXED_RATES[usd_key_from]  # to USD
        rate_to = FIXED_RATES[usd_key_to]      # from USD
        rate = rate_from * rate_to
        result = amount * rate
        return ToolResult(
            "convert_currency",
            True,
            f"{amount:,.2f} {from_curr} = {result:,.2f} {to_curr}\n"
            f"Курс: 1 {from_curr} = {rate:.6f} {to_curr}",
            data={"result": result, "rate": rate},
        )
    
    return ToolResult(
        "convert_currency",
        False,
        f"Курс {from_curr} → {to_curr} недоступен. "
        f"Доступные: USD, TMT (19.5), CNY (7.1)",
        error="Rate not available",
    )


async def tool_get_financial_summary(
    db_session: Any = None,
) -> ToolResult:
    """Финансовая сводка за всё время."""
    if not db_session:
        return ToolResult("get_financial_summary", False, "", error="Нет сессии БД")
    
    try:
        from pds_ultimate.core.database import FinancialRecord, RecordType
        
        # Total income
        total_income = db_session.query(FinancialRecord).filter(
            FinancialRecord.record_type == RecordType.INCOME
        ).count()
        
        # Total expenses
        total_expenses = db_session.query(FinancialRecord).filter(
            FinancialRecord.record_type == RecordType.EXPENSE
        ).count()
        
        # Sum amounts (simplified)
        income_sum = db_session.query(FinancialRecord).filter(
            FinancialRecord.record_type == RecordType.INCOME
        ).all()
        income_total = sum(r.amount for r in income_sum)
        
        expense_sum = db_session.query(FinancialRecord).filter(
            FinancialRecord.record_type == RecordType.EXPENSE
        ).all()
        expense_total = sum(r.amount for r in expense_sum)
        
        summary = f"""
📊 ФИНАНСОВАЯ СВОДКА
═══════════════════════════════

Всего записей:
  • Доходы: {total_income}
  • Расходы: {total_expenses}

Суммы:
  • Общий доход: {income_total:,.2f} USD
  • Общий расход: {expense_total:,.2f} USD
  • Баланс: {income_total - expense_total:,.2f} USD
"""
        
        return ToolResult(
            "get_financial_summary",
            True,
            summary,
            data={
                "total_income_records": total_income,
                "total_expense_records": total_expenses,
                "income_total": income_total,
                "expense_total": expense_total,
                "balance": income_total - expense_total,
            },
        )
        
    except Exception as e:
        logger.error(f"tool_get_financial_summary failed: {e}")
        return ToolResult("get_financial_summary", False, "", error=str(e))


async def tool_export_finance_excel(
    days: int = 30,
    db_session: Any = None,
) -> ToolResult:
    """Экспорт финансов в Excel."""
    if not db_session:
        return ToolResult("export_finance_excel", False, "", error="Нет сессии БД")
    
    try:
        from datetime import datetime
        
        from pds_ultimate.core.database import FinancialRecord
        
        from_date = date.today() - timedelta(days=days)
        
        records = db_session.query(FinancialRecord).filter(
            FinancialRecord.record_date >= from_date
        ).order_by(FinancialRecord.record_date.desc()).all()
        
        if not records:
            return ToolResult(
                "export_finance_excel",
                False,
                f"Нет записей за {days} дней"
            )
        
        # Create Excel (simplified, without openpyxl dependency)
        # In production, use openpyxl or xlsxwriter
        csv_content = "Date,Type,Category,Amount,Currency,Description\n"
        for r in records:
            csv_content += (
                f"{r.record_date},{r.record_type.value},{r.category or ''},"
                f"{r.amount},{r.currency or 'USD'},\"{r.description or ''}\"\n"
            )
        
        # Save to file
        filename = f"finance_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        filepath = f"data/exports/{filename}"
        
        import os
        os.makedirs("data/exports", exist_ok=True)
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(csv_content)
        
        return ToolResult(
            "export_finance_excel",
            True,
            f"✅ Экспорт: {len(records)} записей → {filepath}",
            data={"filepath": filepath, "records_count": len(records)},
        )
        
    except Exception as e:
        logger.error(f"tool_export_finance_excel failed: {e}")
        return ToolResult("export_finance_excel", False, "", error=str(e))


# ─── Tool Registration ───────────────────────────────────────────────────────

def register_finance_tools(registry: ToolRegistry) -> None:
    """Зарегистрировать finance инструменты."""
    
    registry.register(
        Tool(
            name="set_income",
            description="Записать доход (сколько заплатили МНЕ)",
            parameters=[
                ToolParameter("amount", "number", "Сумма"),
                ToolParameter("currency", "string", "Валюта (USD/TMT/CNY)", default="USD"),
                ToolParameter("description", "string", "Описание", required=False),
            ],
            handler=tool_set_income,
            category="finance",
        )
    )
    
    registry.register(
        Tool(
            name="set_expense",
            description="Записать расход (сколько Я заплатил поставщику)",
            parameters=[
                ToolParameter("amount", "number", "Сумма"),
                ToolParameter("currency", "string", "Валюта", default="USD"),
                ToolParameter("description", "string", "Описание", required=False),
                ToolParameter("category", "string", "Категория (goods/delivery/other)", default="goods"),
            ],
            handler=tool_set_expense,
            category="finance",
        )
    )
    
    registry.register(
        Tool(
            name="set_delivery_cost",
            description="Записать стоимость доставки",
            parameters=[
                ToolParameter("amount", "number", "Сумма"),
                ToolParameter("currency", "string", "Валюта", default="USD"),
                ToolParameter("order_number", "string", "Номер заказа", required=False),
            ],
            handler=tool_set_delivery_cost,
            category="finance",
        )
    )
    
    registry.register(
        Tool(
            name="get_profit_report",
            description="Отчёт о прибыли: INCOME - GOODS = REMAINDER - DELIVERY = NET_PROFIT",
            parameters=[
                ToolParameter("days", "number", "Период в днях", default=30, required=False),
            ],
            handler=tool_get_profit_report,
            category="finance",
        )
    )
    
    registry.register(
        Tool(
            name="convert_currency",
            description="Конвертация валют (1 USD = 19.5 TMT, 1 USD = 7.1 CNY)",
            parameters=[
                ToolParameter("amount", "number", "Сумма"),
                ToolParameter("from_currency", "string", "Из валюты"),
                ToolParameter("to_currency", "string", "В валюту"),
            ],
            handler=tool_convert_currency,
            category="finance",
        )
    )
    
    registry.register(
        Tool(
            name="get_financial_summary",
            description="Финансовая сводка за всё время",
            parameters=[],
            handler=tool_get_financial_summary,
            category="finance",
        )
    )
    
    registry.register(
        Tool(
            name="export_finance_excel",
            description="Экспорт финансов в Excel/CSV",
            parameters=[
                ToolParameter("days", "number", "Период в днях", default=30, required=False),
            ],
            handler=tool_export_finance_excel,
            category="finance",
        )
    )


__all__ = [
    "tool_set_income",
    "tool_set_expense",
    "tool_set_delivery_cost",
    "tool_get_profit_report",
    "tool_convert_currency",
    "tool_get_financial_summary",
    "tool_export_finance_excel",
    "register_finance_tools",
]
