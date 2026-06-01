"""
PDS-Ultimate Profit Calculator
==================================
Калькулятор прибыли и распределения.

По ТЗ (формула):
  ДОХОД (сколько заплатили МНЕ)
  - РАСХОД_ТОВАР (сколько Я заплатил поставщику)
  = ОСТАТОК
  - РАСХОД_ДОСТАВКА
  = ЧИСТАЯ_ПРИБЫЛЬ
  → На расходы (expense_percent %)
  → Отложения на будущее (savings_percent %)

❌ НЕ считаем: налоги, комиссии
"""

from __future__ import annotations

from typing import Optional

from pds_ultimate.config import config


class ProfitCalculator:
    """
    Калькулятор прибыли: формула по ТЗ + аналитика.
    """

    def __init__(self, db_session_factory):
        self._session_factory = db_session_factory

    # ═══════════════════════════════════════════════════════════════════════
    # Основная формула
    # ═══════════════════════════════════════════════════════════════════════

    def calculate(
        self,
        income: float,
        expense_goods: float,
        delivery_cost: float = 0.0,
        expense_percent: Optional[float] = None,
        savings_percent: Optional[float] = None,
    ) -> dict:
        """
        Рассчитать чистую прибыль и распределение.
        Все суммы должны быть в одной валюте (USD).
        """
        if expense_percent is None:
            expense_percent = config.finance.expense_percent
        if savings_percent is None:
            savings_percent = config.finance.savings_percent

        remainder = income - expense_goods
        net_profit = remainder - delivery_cost

        to_expenses = round(net_profit * expense_percent / 100.0, 2)
        to_savings = round(net_profit * savings_percent / 100.0, 2)

        margin = (net_profit / income * 100) if income > 0 else 0.0

        return {
            "income": round(income, 2),
            "expense_goods": round(expense_goods, 2),
            "remainder": round(remainder, 2),
            "delivery_cost": round(delivery_cost, 2),
            "net_profit": round(net_profit, 2),
            "expense_percent": expense_percent,
            "savings_percent": savings_percent,
            "to_expenses": to_expenses,
            "to_savings": to_savings,
            "margin_percent": round(margin, 1),
        }

    # ═══════════════════════════════════════════════════════════════════════
    # Аналитика
    # ═══════════════════════════════════════════════════════════════════════

    async def get_profit_analytics(
        self,
        period_months: int = 3,
    ) -> dict:
        """Аналитика прибыли за N последних месяцев."""
        from pds_ultimate.core.database import FinanceSummary

        with self._session_factory() as session:
            summaries = (
                session.query(FinanceSummary)
                .order_by(
                    FinanceSummary.period_year.desc(),
                    FinanceSummary.period_month.desc(),
                )
                .limit(period_months)
                .all()
            )

            if not summaries:
                return {"months": [], "total_profit": 0, "avg_profit": 0}

            months = []
            total_profit = 0.0
            total_orders = 0

            for s in summaries:
                months.append({
                    "period": f"{s.period_year}-{s.period_month:02d}",
                    "income": s.total_income,
                    "expenses": s.total_expense_goods + s.total_expense_delivery,
                    "profit": s.total_net_profit,
                    "orders": s.orders_completed,
                    "margin": (
                        round(s.total_net_profit / s.total_income * 100, 1)
                        if s.total_income > 0 else 0
                    ),
                })
                total_profit += s.total_net_profit
                total_orders += s.orders_completed

            avg_profit = total_profit / len(summaries) if summaries else 0

            return {
                "months": months,
                "total_profit": round(total_profit, 2),
                "avg_monthly_profit": round(avg_profit, 2),
                "total_orders": total_orders,
                "period": f"Последние {len(summaries)} мес.",
            }

    async def get_order_profitability(
        self,
        limit: int = 10,
    ) -> list[dict]:
        """Топ заказов по прибыльности."""
        from pds_ultimate.core.database import Order, OrderStatus

        with self._session_factory() as session:
            orders = (
                session.query(Order)
                .filter(
                    Order.net_profit.isnot(None),
                    Order.status.in_([
                        OrderStatus.COMPLETED, OrderStatus.ARCHIVED,
                    ]),
                )
                .order_by(Order.net_profit.desc())
                .limit(limit)
                .all()
            )

            return [
                {
                    "order_number": o.order_number,
                    "income": o.income,
                    "expense_goods": o.expense_goods,
                    "delivery": o.delivery_cost,
                    "net_profit": o.net_profit,
                    "margin": (
                        round(o.net_profit / o.income * 100, 1)
                        if o.income and o.income > 0 else 0
                    ),
                    "date": (
                        o.completed_date.isoformat()
                        if o.completed_date else None
                    ),
                }
                for o in orders
            ]

    # ═══════════════════════════════════════════════════════════════════════
    # Форматирование
    # ═══════════════════════════════════════════════════════════════════════

    def format_calculation(self, result: dict) -> str:
        """Красивый вывод расчёта прибыли."""
        lines = [
            "📊 Расчёт прибыли:\n",
            f"💰 Доход:         ${result['income']:,.2f}",
            f"📦 Товар:        -${result['expense_goods']:,.2f}",
            "                  ─────────────",
            f"   Остаток:       ${result['remainder']:,.2f}",
            f"🚚 Доставка:     -${result['delivery_cost']:,.2f}",
            "                  ═════════════",
            f"💎 Чистая прибыль: ${result['net_profit']:,.2f}  "
            f"({result['margin_percent']}%)\n",
            f"💳 На расходы ({result['expense_percent']}%):  "
            f"${result['to_expenses']:,.2f}",
            f"🏦 Отложения ({result['savings_percent']}%):  "
            f"${result['to_savings']:,.2f}",
        ]
        return "\n".join(lines)

    def format_analytics(self, analytics: dict) -> str:
        """Форматирование аналитики."""
        if not analytics.get("months"):
            return "📊 Недостаточно данных для аналитики."

        lines = [
            f"📊 Аналитика прибыли ({analytics['period']}):\n",
        ]

        for m in analytics["months"]:
            lines.append(
                f"  {m['period']}: прибыль ${m['profit']:,.2f} "
                f"({m['margin']}%) | {m['orders']} заказов"
            )

        lines.append(f"\n💰 Итого прибыль: ${analytics['total_profit']:,.2f}")
        lines.append(
            f"📈 Среднемесячная: ${analytics['avg_monthly_profit']:,.2f}"
        )

        return "\n".join(lines)
