"""
PDS-Ultimate Master Finance
===============================
Главная книга финансов.

По ТЗ:
- Master_Finance.xlsx — НИКОГДА не удаляется
- Разделы: Оборот, Расходы на товар, Доставка, Чистая прибыль,
  На расходы (%), Отложения (%), Личные расходы (сканер чеков)
- Sync Logic: Файл = ЭТАЛОН, БД подстраивается
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pds_ultimate.config import (
    MASTER_FINANCE_PATH,
    config,
    logger,
)


class MasterFinance:
    """
    Главная финансовая книга: баланс, прибыль, расходы, отложения.
    """

    def __init__(self, db_session_factory):
        self._session_factory = db_session_factory

    # ═══════════════════════════════════════════════════════════════════════
    # Запись транзакции
    # ═══════════════════════════════════════════════════════════════════════

    async def record_transaction(
        self,
        transaction_type: str,
        amount: float,
        currency: str = "USD",
        description: str = "",
        category: Optional[str] = None,
        order_id: Optional[int] = None,
    ) -> dict:
        """
        Записать произвольную транзакцию.
        transaction_type: income, expense_goods, expense_delivery,
                          expense_personal, profit_expenses, profit_savings
        """
        from pds_ultimate.core.database import Transaction, TransactionType

        type_map = {
            "income": TransactionType.INCOME,
            "expense_goods": TransactionType.EXPENSE_GOODS,
            "expense_delivery": TransactionType.EXPENSE_DELIVERY,
            "expense_personal": TransactionType.EXPENSE_PERSONAL,
            "profit_expenses": TransactionType.PROFIT_EXPENSES,
            "profit_savings": TransactionType.PROFIT_SAVINGS,
        }

        tx_type = type_map.get(transaction_type)
        if not tx_type:
            return {"error": f"Неизвестный тип транзакции: {transaction_type}"}

        # Конвертация в USD
        amount_usd = await self._to_usd(amount, currency)
        rate = amount_usd / amount if amount != 0 else 1.0

        with self._session_factory() as session:
            tx = Transaction(
                order_id=order_id,
                transaction_type=tx_type,
                amount=amount,
                currency=currency,
                amount_usd=amount_usd,
                exchange_rate=rate,
                description=description,
                category=category,
                transaction_date=date.today(),
            )
            session.add(tx)
            session.commit()

            # Пересчитать сводку за текущий месяц
            await self._update_monthly_summary(session)

            logger.info(
                f"Transaction recorded: {tx_type.value} "
                f"{amount} {currency} (${amount_usd:.2f})"
            )

            return {
                "transaction_id": tx.id,
                "type": tx_type.value,
                "amount": amount,
                "currency": currency,
                "amount_usd": round(amount_usd, 2),
            }

    # ═══════════════════════════════════════════════════════════════════════
    # Личные расходы (сканер чеков)
    # ═══════════════════════════════════════════════════════════════════════

    async def add_personal_expense(
        self,
        amount: float,
        currency: str = "USD",
        category: str = "Личные",
        description: str = "",
    ) -> dict:
        """Добавить личный расход (из чека, голосом и т.д.)."""
        return await self.record_transaction(
            transaction_type="expense_personal",
            amount=amount,
            currency=currency,
            description=description,
            category=category,
        )

    # ═══════════════════════════════════════════════════════════════════════
    # Баланс и сводки
    # ═══════════════════════════════════════════════════════════════════════

    async def get_balance(self) -> dict:
        """Текущий баланс: итого по всем категориям."""
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
            total_to_expenses = _sum_type(TransactionType.PROFIT_EXPENSES)
            total_to_savings = _sum_type(TransactionType.PROFIT_SAVINGS)

            net_profit = total_income - total_goods - total_delivery
            available = total_to_expenses - total_personal

            return {
                "total_income": round(total_income, 2),
                "total_expense_goods": round(total_goods, 2),
                "total_expense_delivery": round(total_delivery, 2),
                "total_net_profit": round(net_profit, 2),
                "total_to_expenses": round(total_to_expenses, 2),
                "total_to_savings": round(total_to_savings, 2),
                "total_personal_expenses": round(total_personal, 2),
                "available_for_expenses": round(available, 2),
            }

    async def get_monthly_summary(
        self,
        year: Optional[int] = None,
        month: Optional[int] = None,
    ) -> dict:
        """Сводка за конкретный месяц."""
        from pds_ultimate.core.database import FinanceSummary

        if year is None:
            year = date.today().year
        if month is None:
            month = date.today().month

        with self._session_factory() as session:
            summary = (
                session.query(FinanceSummary)
                .filter(
                    FinanceSummary.period_year == year,
                    FinanceSummary.period_month == month,
                )
                .first()
            )

            if not summary:
                return {
                    "year": year,
                    "month": month,
                    "total_income": 0.0,
                    "total_expense_goods": 0.0,
                    "total_expense_delivery": 0.0,
                    "total_net_profit": 0.0,
                    "orders_completed": 0,
                }

            return {
                "year": year,
                "month": month,
                "total_income": summary.total_income,
                "total_expense_goods": summary.total_expense_goods,
                "total_expense_delivery": summary.total_expense_delivery,
                "total_expense_personal": summary.total_expense_personal,
                "total_net_profit": summary.total_net_profit,
                "total_to_expenses": summary.total_to_expenses,
                "total_to_savings": summary.total_to_savings,
                "orders_completed": summary.orders_completed,
            }

    async def get_recent_transactions(
        self,
        limit: int = 20,
        tx_type: Optional[str] = None,
    ) -> list[dict]:
        """Последние транзакции."""
        from pds_ultimate.core.database import Transaction, TransactionType

        with self._session_factory() as session:
            query = session.query(Transaction)

            if tx_type:
                type_map = {
                    "income": TransactionType.INCOME,
                    "expense_goods": TransactionType.EXPENSE_GOODS,
                    "expense_delivery": TransactionType.EXPENSE_DELIVERY,
                    "expense_personal": TransactionType.EXPENSE_PERSONAL,
                }
                tt = type_map.get(tx_type)
                if tt:
                    query = query.filter(Transaction.transaction_type == tt)

            transactions = (
                query
                .order_by(Transaction.transaction_date.desc())
                .limit(limit)
                .all()
            )

            return [
                {
                    "id": tx.id,
                    "type": tx.transaction_type.value,
                    "amount": tx.amount,
                    "currency": tx.currency,
                    "amount_usd": tx.amount_usd,
                    "description": tx.description,
                    "category": tx.category,
                    "date": tx.transaction_date.isoformat(),
                    "order_id": tx.order_id,
                }
                for tx in transactions
            ]

    # ═══════════════════════════════════════════════════════════════════════
    # Master Finance Excel
    # ═══════════════════════════════════════════════════════════════════════

    async def export_master_finance(self) -> str:
        """
        Экспортировать Master_Finance.xlsx.
        Возвращает путь к файлу.
        """
        try:
            import xlsxwriter

            path = str(MASTER_FINANCE_PATH)
            wb = xlsxwriter.Workbook(path)

            # Форматы
            header_fmt = wb.add_format({
                "bold": True,
                "bg_color": "#4472C4",
                "font_color": "#FFFFFF",
                "border": 1,
            })
            money_fmt = wb.add_format({"num_format": "$#,##0.00", "border": 1})
            text_fmt = wb.add_format({"border": 1})
            date_fmt = wb.add_format({"num_format": "yyyy-mm-dd", "border": 1})

            # === Лист 1: Сводка ===
            ws1 = wb.add_worksheet("Сводка")
            balance = await self.get_balance()

            rows = [
                ("Оборот (доход)", balance["total_income"]),
                ("Расходы на товар", balance["total_expense_goods"]),
                ("Расходы на доставку", balance["total_expense_delivery"]),
                ("Чистая прибыль", balance["total_net_profit"]),
                ("На расходы", balance["total_to_expenses"]),
                ("Отложения", balance["total_to_savings"]),
                ("Личные расходы", balance["total_personal_expenses"]),
                ("Доступно на расходы", balance["available_for_expenses"]),
            ]

            ws1.write(0, 0, "Категория", header_fmt)
            ws1.write(0, 1, "Сумма (USD)", header_fmt)
            ws1.set_column(0, 0, 25)
            ws1.set_column(1, 1, 15)

            for i, (label, value) in enumerate(rows, 1):
                ws1.write(i, 0, label, text_fmt)
                ws1.write(i, 1, value, money_fmt)

            # === Лист 2: Транзакции ===
            ws2 = wb.add_worksheet("Транзакции")
            headers = ["Дата", "Тип", "Сумма", "Валюта",
                       "USD", "Описание", "Категория"]
            for col, h in enumerate(headers):
                ws2.write(0, col, h, header_fmt)

            ws2.set_column(0, 0, 12)
            ws2.set_column(1, 1, 18)
            ws2.set_column(2, 2, 12)
            ws2.set_column(4, 4, 12)
            ws2.set_column(5, 5, 40)
            ws2.set_column(6, 6, 15)

            txs = await self.get_recent_transactions(limit=1000)
            for i, tx in enumerate(txs, 1):
                ws2.write(i, 0, tx["date"], date_fmt)
                ws2.write(i, 1, tx["type"], text_fmt)
                ws2.write(i, 2, tx["amount"], money_fmt)
                ws2.write(i, 3, tx["currency"], text_fmt)
                ws2.write(i, 4, tx["amount_usd"] or 0, money_fmt)
                ws2.write(i, 5, tx["description"] or "", text_fmt)
                ws2.write(i, 6, tx["category"] or "", text_fmt)

            # === Лист 3: По месяцам ===
            ws3 = wb.add_worksheet("По месяцам")
            month_headers = [
                "Период", "Доход", "Товар", "Доставка", "Личные",
                "Прибыль", "На расходы", "Отложения", "Заказов",
            ]
            for col, h in enumerate(month_headers):
                ws3.write(0, col, h, header_fmt)

            from pds_ultimate.core.database import FinanceSummary

            with self._session_factory() as session:
                summaries = (
                    session.query(FinanceSummary)
                    .order_by(
                        FinanceSummary.period_year.desc(),
                        FinanceSummary.period_month.desc(),
                    )
                    .all()
                )

                for i, s in enumerate(summaries, 1):
                    ws3.write(
                        i, 0, f"{s.period_year}-{s.period_month:02d}", text_fmt)
                    ws3.write(i, 1, s.total_income, money_fmt)
                    ws3.write(i, 2, s.total_expense_goods, money_fmt)
                    ws3.write(i, 3, s.total_expense_delivery, money_fmt)
                    ws3.write(i, 4, s.total_expense_personal, money_fmt)
                    ws3.write(i, 5, s.total_net_profit, money_fmt)
                    ws3.write(i, 6, s.total_to_expenses, money_fmt)
                    ws3.write(i, 7, s.total_to_savings, money_fmt)
                    ws3.write(i, 8, s.orders_completed, text_fmt)

            wb.close()
            logger.info(f"Master Finance exported: {path}")
            return path

        except Exception as e:
            logger.error(f"Master Finance export failed: {e}")
            raise

    # ═══════════════════════════════════════════════════════════════════════
    # Форматирование
    # ═══════════════════════════════════════════════════════════════════════

    def format_balance(self, balance: dict) -> str:
        """Человекочитаемый баланс."""
        return (
            f"💰 Финансовая сводка:\n"
            f"\n"
            f"📈 Оборот: ${balance['total_income']:,.2f}\n"
            f"📦 Товары: -${balance['total_expense_goods']:,.2f}\n"
            f"🚚 Доставка: -${balance['total_expense_delivery']:,.2f}\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"💎 Чистая прибыль: ${balance['total_net_profit']:,.2f}\n"
            f"\n"
            f"💳 На расходы: ${balance['total_to_expenses']:,.2f}\n"
            f"🏦 Отложения: ${balance['total_to_savings']:,.2f}\n"
            f"🛒 Личные расходы: -${balance['total_personal_expenses']:,.2f}\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"✅ Доступно: ${balance['available_for_expenses']:,.2f}"
        )

    # ═══════════════════════════════════════════════════════════════════════
    # Internal
    # ═══════════════════════════════════════════════════════════════════════

    async def _update_monthly_summary(self, session) -> None:
        """Пересчитать сводку за текущий месяц."""
        from sqlalchemy import extract, func

        from pds_ultimate.core.database import (
            FinanceSummary,
            Order,
            OrderStatus,
            Transaction,
            TransactionType,
        )

        today = date.today()
        year = today.year
        month = today.month

        # Получить или создать запись сводки
        summary = (
            session.query(FinanceSummary)
            .filter(
                FinanceSummary.period_year == year,
                FinanceSummary.period_month == month,
            )
            .first()
        )

        if not summary:
            summary = FinanceSummary(
                period_year=year,
                period_month=month,
            )
            session.add(summary)

        def _month_sum(tx_type: TransactionType) -> float:
            result = (
                session.query(func.sum(Transaction.amount_usd))
                .filter(
                    Transaction.transaction_type == tx_type,
                    extract("year", Transaction.transaction_date) == year,
                    extract("month", Transaction.transaction_date) == month,
                )
                .scalar()
            )
            return result or 0.0

        summary.total_income = _month_sum(TransactionType.INCOME)
        summary.total_expense_goods = _month_sum(TransactionType.EXPENSE_GOODS)
        summary.total_expense_delivery = _month_sum(
            TransactionType.EXPENSE_DELIVERY)
        summary.total_expense_personal = _month_sum(
            TransactionType.EXPENSE_PERSONAL)
        summary.total_net_profit = (
            summary.total_income
            - summary.total_expense_goods
            - summary.total_expense_delivery
        )
        summary.total_to_expenses = _month_sum(TransactionType.PROFIT_EXPENSES)
        summary.total_to_savings = _month_sum(TransactionType.PROFIT_SAVINGS)

        # Количество закрытых заказов за месяц
        completed = (
            session.query(func.count(Order.id))
            .filter(
                Order.status.in_(
                    [OrderStatus.COMPLETED, OrderStatus.ARCHIVED]),
                extract("year", Order.completed_date) == year,
                extract("month", Order.completed_date) == month,
            )
            .scalar() or 0
        )
        summary.orders_completed = completed

        session.commit()

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
                return amount / rate_record.rate

        fixed = config.currency.fixed_rates.get(currency)
        if fixed and fixed > 0:
            return amount / fixed

        logger.warning(f"No rate for {currency}/USD")
        return amount
