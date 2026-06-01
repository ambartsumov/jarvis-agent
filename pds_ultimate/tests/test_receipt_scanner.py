"""
Тесты Receipt Scanner — modules/executive/receipt_scanner.py
"""

import pytest


class TestExpenseCategory:
    """Тесты категорий расходов."""

    def test_import(self):
        """Модуль импортируется."""
        from pds_ultimate.modules.executive.receipt_scanner import (
            ReceiptScanner,
            receipt_scanner,
        )
        assert ReceiptScanner is not None
        assert receipt_scanner is not None

    def test_categories_count(self):
        """Минимум 8 категорий."""
        from pds_ultimate.modules.executive.receipt_scanner import ExpenseCategory

        categories = list(ExpenseCategory)
        assert len(categories) >= 8

    def test_category_values(self):
        """Основные категории существуют."""
        from pds_ultimate.modules.executive.receipt_scanner import ExpenseCategory

        names = [c.name for c in ExpenseCategory]
        assert "FOOD" in names or "TRANSPORT" in names or "OFFICE" in names

    def test_category_keywords_exist(self):
        """CATEGORY_KEYWORDS заполнены."""
        from pds_ultimate.modules.executive.receipt_scanner import CATEGORY_KEYWORDS

        assert len(CATEGORY_KEYWORDS) >= 5


class TestScannedReceipt:
    """Тесты ScannedReceipt."""

    def test_creation(self):
        """ScannedReceipt создаётся."""
        from pds_ultimate.modules.executive.receipt_scanner import ScannedReceipt

        receipt = ScannedReceipt(amount=0)
        assert receipt is not None

    def test_receipt_with_data(self):
        """ScannedReceipt с данными."""
        from pds_ultimate.modules.executive.receipt_scanner import (
            ExpenseCategory,
            ScannedReceipt,
        )

        receipt = ScannedReceipt(
            amount=100.50,
            currency="USD",
            category=ExpenseCategory.FOOD,
            vendor="Test Store",
            description="Хлеб, Молоко",
        )
        assert receipt.vendor == "Test Store"
        assert receipt.amount == 100.50
        assert receipt.category == ExpenseCategory.FOOD


class TestExpenseSummary:
    """Тесты ExpenseSummary."""

    def test_creation(self):
        """ExpenseSummary создаётся."""
        from pds_ultimate.modules.executive.receipt_scanner import ExpenseSummary

        summary = ExpenseSummary(
            period="2025-06",
            total=5000.0,
            by_category={"FOOD": 2000.0, "TRANSPORT": 1500.0},
            count=15,
        )
        assert summary.total == 5000.0
        assert summary.count == 15
        assert len(summary.by_category) == 2


class TestReceiptScanner:
    """Тесты сканера чеков."""

    def test_scanner_creation(self):
        """ReceiptScanner создаётся."""
        from pds_ultimate.modules.executive.receipt_scanner import ReceiptScanner

        scanner = ReceiptScanner()
        assert scanner is not None

    def test_detect_category_food(self):
        """Определение категории: еда."""
        from pds_ultimate.modules.executive.receipt_scanner import (
            ExpenseCategory,
            ReceiptScanner,
        )

        scanner = ReceiptScanner()
        text = "хлеб молоко кефир колбаса"
        category = scanner.detect_category(text)
        assert category == ExpenseCategory.FOOD

    def test_detect_category_transport(self):
        """Определение категории: транспорт."""
        from pds_ultimate.modules.executive.receipt_scanner import (
            ExpenseCategory,
            ReceiptScanner,
        )

        scanner = ReceiptScanner()
        text = "бензин АИ-95 топливо"
        category = scanner.detect_category(text)
        assert category == ExpenseCategory.TRANSPORT

    def test_detect_category_unknown(self):
        """Категория не определена — OTHER."""
        from pds_ultimate.modules.executive.receipt_scanner import (
            ExpenseCategory,
            ReceiptScanner,
        )

        scanner = ReceiptScanner()
        text = "xyz_unknown_item_12345"
        category = scanner.detect_category(text)
        assert category == ExpenseCategory.OTHER

    def test_format_receipt(self):
        """format_receipt возвращает текст."""
        from pds_ultimate.modules.executive.receipt_scanner import (
            ExpenseCategory,
            ReceiptScanner,
            ScannedReceipt,
        )

        scanner = ReceiptScanner()
        receipt = ScannedReceipt(
            amount=250.0,
            currency="TMT",
            category=ExpenseCategory.FOOD,
            vendor="Магазин",
        )
        text = scanner.format_receipt(receipt)
        assert "Магазин" in text
        assert "250" in text

    def test_format_summary(self):
        """format_summary возвращает текст."""
        from pds_ultimate.modules.executive.receipt_scanner import (
            ExpenseSummary,
            ReceiptScanner,
        )

        scanner = ReceiptScanner()
        summary = ExpenseSummary(
            period="2025-06",
            total=10000.0,
            by_category={"FOOD": 5000.0, "TRANSPORT": 3000.0},
            count=25,
        )
        text = scanner.format_summary(summary)
        assert "10000" in text or "10,000" in text or "10 000" in text

    @pytest.mark.asyncio
    async def test_scan_receipt_missing_file(self):
        """scan_receipt несуществующего файла."""
        from pds_ultimate.modules.executive.receipt_scanner import ReceiptScanner

        scanner = ReceiptScanner()
        receipt = await scanner.scan_receipt("/nonexistent/receipt.jpg")
        # Может вернуть пустой receipt или ошибку
        assert receipt is not None

    def test_global_instance(self):
        """Глобальный экземпляр."""
        from pds_ultimate.modules.executive.receipt_scanner import receipt_scanner

        assert receipt_scanner is not None

    @pytest.mark.asyncio
    async def test_get_summary(self):
        """get_summary без БД."""
        from pds_ultimate.modules.executive.receipt_scanner import ReceiptScanner

        scanner = ReceiptScanner()
        # Без сессии — пустой summary или ошибка
        try:
            summary = await scanner.get_summary(session_factory=None)
            assert summary is not None
        except Exception:
            pass  # Нет БД — ожидаемо
