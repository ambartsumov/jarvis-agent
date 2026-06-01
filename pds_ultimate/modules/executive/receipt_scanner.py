"""
PDS-Ultimate Receipt Scanner
================================
Сканер чеков: фото → OCR → сумма + категория → «Личные расходы».

По ТЗ §7.4:
- Фото чека → OCR → сумма + категория → Master Finance
- Авто-определение категории расхода
- Сохранение в БД как личный расход
- Группировка и отчёты по категориям

Категории:
- Еда и напитки
- Транспорт
- Одежда
- Электроника
- Медицина
- Развлечения
- Дом и быт
- Связь
- Другое
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from pds_ultimate.config import logger

# ─── Categories ──────────────────────────────────────────────────────────────


class ExpenseCategory(str, Enum):
    """Категории личных расходов."""
    FOOD = "Еда и напитки"
    TRANSPORT = "Транспорт"
    CLOTHING = "Одежда"
    ELECTRONICS = "Электроника"
    MEDICINE = "Медицина"
    ENTERTAINMENT = "Развлечения"
    HOME = "Дом и быт"
    COMMUNICATION = "Связь"
    EDUCATION = "Образование"
    BUSINESS = "Бизнес-расходы"
    OTHER = "Другое"


# Ключевые слова для авто-определения категории
CATEGORY_KEYWORDS: dict[ExpenseCategory, list[str]] = {
    ExpenseCategory.FOOD: [
        "ресторан", "кафе", "магазин", "продукт", "еда", "обед",
        "ужин", "завтрак", "кофе", "чай", "пицца", "суши", "burger",
        "food", "cafe", "restaurant", "grocery", "market", "supermarket",
        "хлеб", "молоко", "мясо", "овощ", "фрукт", "вода", "напиток",
        "delivery", "доставка еды", "wolt", "yandex food", "glovo",
        "饭", "餐厅", "超市", "食品",  # китайский
    ],
    ExpenseCategory.TRANSPORT: [
        "такси", "uber", "yandex", "бензин", "метро", "автобус",
        "парковка", "taxi", "fuel", "gas", "parking", "airline",
        "билет", "авиа", "поезд", "train", "flight", "ticket",
        "打车", "出租", "地铁", "公交",  # китайский
    ],
    ExpenseCategory.CLOTHING: [
        "одежда", "обувь", "магазин одежды", "zara", "h&m", "nike",
        "adidas", "clothing", "shoes", "fashion", "футболка", "джинсы",
        "куртка", "платье", "костюм",
        "衣服", "鞋子",  # китайский
    ],
    ExpenseCategory.ELECTRONICS: [
        "электрон", "телефон", "компьютер", "phone", "laptop",
        "apple", "samsung", "xiaomi", "huawei", "техника",
        "зарядка", "наушники", "кабель", "adapter", "headphone",
        "电子", "手机", "电脑",  # китайский
    ],
    ExpenseCategory.MEDICINE: [
        "аптека", "лекарств", "медицин", "врач", "больница",
        "pharmacy", "medicine", "doctor", "hospital", "health",
        "стоматолог", "анализ", "витамин",
        "药店", "医院", "医生",  # китайский
    ],
    ExpenseCategory.ENTERTAINMENT: [
        "кино", "театр", "музей", "парк", "развлечен",
        "cinema", "movie", "theater", "concert", "game",
        "спорт", "фитнес", "gym", "бассейн", "игра",
        "电影", "游戏", "娱乐",  # китайский
    ],
    ExpenseCategory.HOME: [
        "дом", "ремонт", "мебель", "уборка", "стирка",
        "home", "furniture", "repair", "cleaning", "ikea",
        "квартира", "коммуналка", "электричество", "вода",
        "房子", "家具",  # китайский
    ],
    ExpenseCategory.COMMUNICATION: [
        "связь", "телеком", "интернет", "мобил", "сим",
        "telecom", "internet", "mobile", "sim", "phone bill",
        "подписка", "subscription", "netflix", "spotify",
        "电话", "网络",  # китайский
    ],
    ExpenseCategory.EDUCATION: [
        "обучение", "курс", "книга", "образов", "школа",
        "education", "course", "book", "training", "school",
        "university", "lesson", "tutorial", "udemy",
        "教育", "课程", "书",  # китайский
    ],
    ExpenseCategory.BUSINESS: [
        "офис", "канцелярия", "печать", "копия", "визитка",
        "office", "printing", "business", "stationery",
        "командировка", "travel", "hotel", "гостиница",
        "办公", "商务",  # китайский
    ],
}


@dataclass
class ScannedReceipt:
    """Результат сканирования чека."""
    amount: float
    currency: str = "USD"
    category: ExpenseCategory = ExpenseCategory.OTHER
    vendor: Optional[str] = None
    date: Optional[str] = None
    description: str = ""
    confidence: float = 0.0
    raw_text: str = ""
    image_path: str = ""
    saved_to_db: bool = False
    db_id: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "amount": self.amount,
            "currency": self.currency,
            "category": self.category.value,
            "vendor": self.vendor,
            "date": self.date,
            "description": self.description,
            "confidence": round(self.confidence, 3),
            "saved": self.saved_to_db,
        }


@dataclass
class ExpenseSummary:
    """Суммарная статистика расходов."""
    total: float = 0.0
    currency: str = "USD"
    by_category: dict[str, float] = field(default_factory=dict)
    count: int = 0
    period: str = ""

    def to_dict(self) -> dict:
        return {
            "total": round(self.total, 2),
            "currency": self.currency,
            "categories": self.by_category,
            "count": self.count,
            "period": self.period,
        }


# ─── Receipt Scanner ────────────────────────────────────────────────────────

class ReceiptScanner:
    """
    Сканер чеков с авто-категоризацией.

    Workflow:
    1. Фото → OCR Engine → текст
    2. Извлечение суммы (regex patterns)
    3. Авто-определение категории (keyword matching)
    4. Сохранение в БД → Master Finance (личные расходы)
    5. Отчёты и группировка по категориям

    Использование:
        receipt = await scanner.scan_receipt("photo.jpg")
        saved = await scanner.save_expense(receipt, session_factory)
        summary = await scanner.get_summary(session_factory, "2026-02")
    """

    def __init__(self):
        self._scan_count = 0
        self._total_scanned = 0.0

    # ═══════════════════════════════════════════════════════════════════════
    # Scanning
    # ═══════════════════════════════════════════════════════════════════════

    async def scan_receipt(
        self,
        image_path: str,
        category_hint: Optional[str] = None,
        currency_hint: Optional[str] = None,
    ) -> ScannedReceipt:
        """
        Сканировать чек: фото → сумма + категория.

        Args:
            image_path: Путь к фото чека
            category_hint: Подсказка категории от пользователя
            currency_hint: Подсказка валюты
        """
        from pds_ultimate.modules.files.ocr_engine import ocr_engine

        # 1. OCR
        ocr_result = await ocr_engine.recognize(image_path)

        if not ocr_result.success:
            logger.warning(
                f"[ReceiptScanner] OCR failed: {ocr_result.error}"
            )
            return ScannedReceipt(
                amount=0,
                description=f"OCR ошибка: {ocr_result.error}",
                image_path=image_path,
            )

        # 2. Извлечение данных
        receipt_data = ocr_engine.extract_receipt(ocr_result)

        # 3. Определение суммы
        amount = receipt_data.total_amount
        currency = currency_hint or (
            receipt_data.total.currency if receipt_data.total else "USD"
        )

        # 4. Категоризация
        if category_hint:
            category = self._match_category_hint(category_hint)
        else:
            category = self.detect_category(ocr_result.full_text)

        # 5. Результат
        self._scan_count += 1
        self._total_scanned += amount

        return ScannedReceipt(
            amount=amount,
            currency=currency,
            category=category,
            vendor=receipt_data.vendor,
            date=receipt_data.date or datetime.now().strftime("%Y-%m-%d"),
            description=self._generate_description(receipt_data),
            confidence=ocr_result.avg_confidence,
            raw_text=ocr_result.full_text,
            image_path=image_path,
        )

    async def scan_receipt_bytes(
        self,
        image_bytes: bytes,
        filename: str = "receipt.jpg",
        category_hint: Optional[str] = None,
        currency_hint: Optional[str] = None,
    ) -> ScannedReceipt:
        """Сканировать чек из байтов."""
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(
            suffix=Path(filename).suffix or ".jpg",
            delete=False,
        ) as tmp:
            tmp.write(image_bytes)
            tmp_path = tmp.name

        try:
            return await self.scan_receipt(
                tmp_path, category_hint, currency_hint
            )
        finally:
            from pathlib import Path as P
            P(tmp_path).unlink(missing_ok=True)

    # ═══════════════════════════════════════════════════════════════════════
    # Category Detection
    # ═══════════════════════════════════════════════════════════════════════

    def detect_category(self, text: str) -> ExpenseCategory:
        """
        Авто-определение категории расхода по тексту чека.
        Считает совпадения ключевых слов, выбирает лучшую категорию.
        """
        text_lower = text.lower()
        scores: dict[ExpenseCategory, int] = {}

        for category, keywords in CATEGORY_KEYWORDS.items():
            score = 0
            for kw in keywords:
                if kw.lower() in text_lower:
                    score += 1
            if score > 0:
                scores[category] = score

        if scores:
            return max(scores, key=scores.get)

        return ExpenseCategory.OTHER

    # ═══════════════════════════════════════════════════════════════════════
    # Save to DB
    # ═══════════════════════════════════════════════════════════════════════

    async def save_expense(
        self,
        receipt: ScannedReceipt,
        session_factory,
        user_id: int = 0,
    ) -> ScannedReceipt:
        """
        Сохранить расход в БД.
        Записывается как личный расход в системе финансов.
        """
        from pds_ultimate.core.database import PersonalExpense

        try:
            with session_factory() as session:
                expense = PersonalExpense(
                    user_id=user_id,
                    amount=receipt.amount,
                    currency=receipt.currency,
                    category=receipt.category.value,
                    vendor=receipt.vendor or "",
                    description=receipt.description,
                    receipt_image=receipt.image_path,
                    expense_date=datetime.now(),
                )
                session.add(expense)
                session.commit()

                receipt.saved_to_db = True
                receipt.db_id = expense.id

                logger.info(
                    f"[ReceiptScanner] Saved expense: "
                    f"{receipt.amount} {receipt.currency} "
                    f"[{receipt.category.value}]"
                )

        except Exception as e:
            logger.warning(f"[ReceiptScanner] Save failed: {e}")
            # Не блокируем — БД может не иметь этой таблицы
            receipt.saved_to_db = False

        return receipt

    # ═══════════════════════════════════════════════════════════════════════
    # Reports
    # ═══════════════════════════════════════════════════════════════════════

    async def get_summary(
        self,
        session_factory,
        period: Optional[str] = None,
        user_id: int = 0,
    ) -> ExpenseSummary:
        """
        Получить суммарные расходы за период.

        Args:
            period: "2026-02" (месяц) или "2026-02-12" (день) или None (все)
        """
        from pds_ultimate.core.database import PersonalExpense

        summary = ExpenseSummary(period=period or "all")

        try:
            with session_factory() as session:
                query = session.query(PersonalExpense)

                if user_id:
                    query = query.filter(
                        PersonalExpense.user_id == user_id
                    )

                if period:
                    # Фильтр по периоду (начало строки даты)
                    query = query.filter(
                        PersonalExpense.expense_date.isoformat().startswith(
                            period
                        )
                    )

                expenses = query.all()

                for exp in expenses:
                    summary.total += exp.amount
                    summary.count += 1
                    cat = exp.category or "Другое"
                    summary.by_category[cat] = (
                        summary.by_category.get(cat, 0) + exp.amount
                    )

        except Exception as e:
            logger.warning(f"[ReceiptScanner] Summary failed: {e}")

        return summary

    # ═══════════════════════════════════════════════════════════════════════
    # Formatting
    # ═══════════════════════════════════════════════════════════════════════

    def format_receipt(self, receipt: ScannedReceipt) -> str:
        """Форматировать результат сканирования для бота."""
        lines = ["🧾 Чек распознан:\n"]

        lines.append(
            f"  💰 Сумма: {receipt.amount:.2f} {receipt.currency}"
        )
        lines.append(f"  📂 Категория: {receipt.category.value}")

        if receipt.vendor:
            lines.append(f"  🏪 Продавец: {receipt.vendor}")
        if receipt.date:
            lines.append(f"  📅 Дата: {receipt.date}")

        conf_pct = int(receipt.confidence * 100)
        lines.append(f"  🎯 Уверенность: {conf_pct}%")

        if receipt.saved_to_db:
            lines.append("\n  ✅ Сохранено в личные расходы")
        else:
            lines.append("\n  ⏳ Не сохранено (подтвердите)")

        return "\n".join(lines)

    def format_summary(self, summary: ExpenseSummary) -> str:
        """Форматировать отчёт по расходам."""
        lines = [f"📊 Расходы ({summary.period}):\n"]
        lines.append(
            f"  💰 Всего: {summary.total:.2f} {summary.currency}"
        )
        lines.append(f"  📝 Чеков: {summary.count}\n")

        if summary.by_category:
            lines.append("  По категориям:")
            sorted_cats = sorted(
                summary.by_category.items(),
                key=lambda x: x[1],
                reverse=True,
            )
            for cat, amount in sorted_cats:
                pct = (amount / summary.total * 100) if summary.total else 0
                lines.append(
                    f"    • {cat}: {amount:.2f} ({pct:.0f}%)"
                )

        return "\n".join(lines)

    def get_stats(self) -> dict:
        """Статистика сканера."""
        return {
            "scans_total": self._scan_count,
            "total_scanned_amount": round(self._total_scanned, 2),
        }

    # ═══════════════════════════════════════════════════════════════════════
    # Internal
    # ═══════════════════════════════════════════════════════════════════════

    def _match_category_hint(self, hint: str) -> ExpenseCategory:
        """Определить категорию из подсказки пользователя."""
        hint_lower = hint.lower()

        # Прямое совпадение по значению enum
        for cat in ExpenseCategory:
            if hint_lower in cat.value.lower():
                return cat

        # По ключевым словам
        return self.detect_category(hint)

    def _generate_description(self, receipt_data) -> str:
        """Генерировать описание расхода из данных чека."""
        parts = []

        if receipt_data.vendor:
            parts.append(receipt_data.vendor)
        if receipt_data.date:
            parts.append(receipt_data.date)
        if receipt_data.items:
            items_str = ", ".join(
                str(item.get("name", "?")) for item in receipt_data.items[:3]
            )
            parts.append(items_str)

        return " | ".join(parts) if parts else "Чек"


# ─── Глобальный экземпляр ────────────────────────────────────────────────────

receipt_scanner = ReceiptScanner()
