"""
PDS-Ultimate Formatters
=========================
Централизованное форматирование сообщений для Telegram-бота.

Единый стиль:
- Emoji + заголовок
- Разделители
- Таблицы
- Статусы
- Финансы
- Даты
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional, Union

# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

# Статус-эмодзи
STATUS_EMOJI = {
    "success": "✅",
    "error": "❌",
    "warning": "⚠️",
    "info": "ℹ️",
    "pending": "⏳",
    "active": "🟢",
    "paused": "🟡",
    "stopped": "🔴",
    "arrived": "📦",
    "shipped": "🚚",
    "confirmed": "✅",
    "archived": "📁",
    "completed": "🏁",
    "new": "🆕",
}

# Валюты
CURRENCY_SYMBOLS = {
    "USD": "$",
    "CNY": "¥",
    "TMT": "M",
    "EUR": "€",
    "RUB": "₽",
    "GBP": "£",
}

SEPARATOR_THIN = "─" * 25
SEPARATOR_BOLD = "━" * 25
SEPARATOR_DOUBLE = "═" * 25


# ═══════════════════════════════════════════════════════════════════════════════
# MESSAGE FORMATTERS
# ═══════════════════════════════════════════════════════════════════════════════

def format_header(title: str, emoji: str = "📋") -> str:
    """Заголовок с эмодзи."""
    return f"{emoji} {title.upper()}"


def format_section(title: str, content: str, emoji: str = "📌") -> str:
    """Секция с заголовком и содержимым."""
    return f"{emoji} {title}\n{SEPARATOR_THIN}\n{content}"


def format_status(status: str, text: str = "") -> str:
    """Статус с эмодзи."""
    emoji = STATUS_EMOJI.get(status.lower(), "•")
    if text:
        return f"{emoji} {text}"
    return f"{emoji} {status}"


def format_success(text: str) -> str:
    """Успех."""
    return f"✅ {text}"


def format_error(text: str) -> str:
    """Ошибка."""
    return f"❌ {text}"


def format_warning(text: str) -> str:
    """Предупреждение."""
    return f"⚠️ {text}"


# ═══════════════════════════════════════════════════════════════════════════════
# FINANCIAL FORMATTERS
# ═══════════════════════════════════════════════════════════════════════════════

def format_money(
    amount: float,
    currency: str = "USD",
    show_sign: bool = False,
) -> str:
    """
    Форматировать денежную сумму.

    Examples:
        format_money(1500.5)         → "$1,500.50"
        format_money(1500, "CNY")    → "¥1,500.00"
        format_money(-300, show_sign=True) → "-$300.00"
    """
    symbol = CURRENCY_SYMBOLS.get(currency, currency + " ")
    sign = ""
    if show_sign and amount > 0:
        sign = "+"
    elif amount < 0:
        sign = "-"
        amount = abs(amount)

    formatted = f"{amount:,.2f}"
    return f"{sign}{symbol}{formatted}"


def format_profit(
    income: float,
    expenses: float,
    currency: str = "USD",
) -> str:
    """Форматировать строку прибыли."""
    profit = income - expenses
    emoji = "📈" if profit >= 0 else "📉"
    return (
        f"💰 Доход: {format_money(income, currency)}\n"
        f"💸 Расходы: {format_money(expenses, currency)}\n"
        f"{SEPARATOR_THIN}\n"
        f"{emoji} Прибыль: {format_money(profit, currency, show_sign=True)}"
    )


def format_percentage(
    value: float,
    total: float,
    label: str = "",
) -> str:
    """Форматировать процент."""
    if total == 0:
        pct = 0.0
    else:
        pct = (value / total) * 100
    text = f"{pct:.1f}%"
    if label:
        text = f"{label}: {text}"
    return text


# ═══════════════════════════════════════════════════════════════════════════════
# DATE & TIME FORMATTERS
# ═══════════════════════════════════════════════════════════════════════════════

def format_date(
    dt: Union[date, datetime],
    include_time: bool = True,
) -> str:
    """
    Форматировать дату.

    Examples:
        format_date(datetime.now())  → "25.12.2025 14:30"
        format_date(date.today(), include_time=False) → "25.12.2025"
    """
    if isinstance(dt, datetime) and include_time:
        return dt.strftime("%d.%m.%Y %H:%M")
    if isinstance(dt, datetime):
        return dt.strftime("%d.%m.%Y")
    return dt.strftime("%d.%m.%Y")


def format_relative_date(dt: Union[date, datetime]) -> str:
    """
    Относительная дата.

    Examples:
        format_relative_date(today) → "сегодня"
        format_relative_date(yesterday) → "вчера"
        format_relative_date(3_days_ago) → "3 дня назад"
    """
    now = date.today()
    target = dt.date() if isinstance(dt, datetime) else dt
    delta = (now - target).days

    if delta == 0:
        return "сегодня"
    elif delta == 1:
        return "вчера"
    elif delta == -1:
        return "завтра"
    elif delta < 0:
        return f"через {abs(delta)} дн."
    elif delta < 7:
        return f"{delta} дн. назад"
    elif delta < 30:
        weeks = delta // 7
        return f"{weeks} нед. назад"
    elif delta < 365:
        months = delta // 30
        return f"{months} мес. назад"
    else:
        years = delta // 365
        return f"{years} г. назад"


def format_duration(seconds: float) -> str:
    """
    Форматировать длительность.

    Examples:
        format_duration(65)   → "1 мин 5 сек"
        format_duration(3700) → "1 ч 1 мин"
    """
    if seconds < 1:
        return f"{seconds * 1000:.0f} мс"
    if seconds < 60:
        return f"{seconds:.0f} сек"
    if seconds < 3600:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        if secs:
            return f"{mins} мин {secs} сек"
        return f"{mins} мин"

    hours = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    if mins:
        return f"{hours} ч {mins} мин"
    return f"{hours} ч"


# ═══════════════════════════════════════════════════════════════════════════════
# TABLE FORMATTERS
# ═══════════════════════════════════════════════════════════════════════════════

def format_table(
    headers: list[str],
    rows: list[list[str]],
    max_col_width: int = 20,
) -> str:
    """
    Простая текстовая таблица для Telegram.

    format_table(
        ["Товар", "Кол-во", "Цена"],
        [["Маски", "100", "$200"], ["Перчатки", "50", "$150"]]
    )
    """
    if not headers and not rows:
        return ""

    # Определяем ширину колонок
    col_count = len(headers) if headers else (len(rows[0]) if rows else 0)
    widths = [0] * col_count

    if headers:
        for i, h in enumerate(headers):
            widths[i] = min(len(str(h)), max_col_width)

    for row in rows:
        for i, cell in enumerate(row[:col_count]):
            widths[i] = max(widths[i], min(len(str(cell)), max_col_width))

    def _format_row(cells: list[str]) -> str:
        parts = []
        for i, cell in enumerate(cells[:col_count]):
            text = str(cell)[:max_col_width]
            parts.append(text.ljust(widths[i]))
        return " | ".join(parts)

    lines = []
    if headers:
        lines.append(_format_row(headers))
        lines.append("-+-".join("-" * w for w in widths))

    for row in rows:
        lines.append(_format_row(row))

    return "\n".join(lines)


def format_list(
    items: list[str],
    numbered: bool = False,
    bullet: str = "•",
) -> str:
    """Форматировать список."""
    lines = []
    for i, item in enumerate(items, 1):
        if numbered:
            lines.append(f"  {i}. {item}")
        else:
            lines.append(f"  {bullet} {item}")
    return "\n".join(lines)


def format_key_value(
    data: dict,
    separator: str = ":",
) -> str:
    """
    Форматировать пары ключ-значение.

    format_key_value({"Имя": "Славик", "Статус": "VIP"})
    → "Имя: Славик\nСтатус: VIP"
    """
    lines = []
    max_key = max(len(str(k)) for k in data.keys()) if data else 0
    for key, value in data.items():
        lines.append(f"{str(key).ljust(max_key)}{separator} {value}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# COMPOSITE FORMATTERS
# ═══════════════════════════════════════════════════════════════════════════════

def format_order_summary(
    order_number: str,
    status: str,
    items_count: int,
    total: Optional[float] = None,
    currency: str = "USD",
) -> str:
    """Сводка заказа."""
    emoji = STATUS_EMOJI.get(status.lower(), "📦")
    text = f"{emoji} {order_number} | {status} | {items_count} поз."
    if total is not None:
        text += f" | {format_money(total, currency)}"
    return text


def format_brief(
    title: str,
    sections: dict[str, str],
    footer: str = "",
) -> str:
    """
    Форматированный брифинг.

    format_brief("УТРЕННИЙ БРИФИНГ", {
        "📦 Заказы": "5 активных",
        "💰 Баланс": "$1,500.00",
    })
    """
    lines = [format_header(title, "📋"), ""]

    for section_title, content in sections.items():
        lines.append(f"{section_title}: {content}")

    if footer:
        lines.append("")
        lines.append(SEPARATOR_THIN)
        lines.append(footer)

    return "\n".join(lines)


def truncate(text: str, max_length: int = 200, suffix: str = "...") -> str:
    """Обрезать текст с суффиксом."""
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix


def escape_markdown(text: str) -> str:
    """Экранировать спецсимволы Markdown V2."""
    special = r"_*[]()~`>#+-=|{}.!"
    for char in special:
        text = text.replace(char, f"\\{char}")
    return text
