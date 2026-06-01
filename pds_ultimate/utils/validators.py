"""
PDS-Ultimate Validators
=========================
Централизованная валидация данных.

Валидаторы:
- Телефоны (международный формат)
- Email
- Валюты и суммы
- Даты
- Tracking-номера
- Файлы
- Текст
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import Optional, Union

# ═══════════════════════════════════════════════════════════════════════════════
# PHONE VALIDATORS
# ═══════════════════════════════════════════════════════════════════════════════

# Туркменистан: +993XXXXXXXX (12 цифр всего)
# Китай: +86XXXXXXXXXXX (13 цифр)
# Россия: +7XXXXXXXXXX (12 цифр)
PHONE_PATTERNS = [
    re.compile(r"^\+993\d{8}$"),         # TM
    re.compile(r"^\+86\d{11}$"),         # CN
    re.compile(r"^\+7\d{10}$"),          # RU
    re.compile(r"^\+\d{10,15}$"),        # International
]


def is_valid_phone(phone: str) -> bool:
    """Проверить номер телефона."""
    cleaned = re.sub(r"[\s\-\(\)]", "", phone)
    return any(p.match(cleaned) for p in PHONE_PATTERNS)


def normalize_phone(phone: str) -> str:
    """Нормализовать номер: +XXXXXXXXXXX."""
    cleaned = re.sub(r"[\s\-\(\)]", "", phone)
    if not cleaned.startswith("+"):
        if cleaned.startswith("8") and len(cleaned) == 11:
            cleaned = "+7" + cleaned[1:]
        elif cleaned.startswith("993"):
            cleaned = "+" + cleaned
        elif cleaned.startswith("86"):
            cleaned = "+" + cleaned
        else:
            cleaned = "+" + cleaned
    return cleaned


# ═══════════════════════════════════════════════════════════════════════════════
# EMAIL VALIDATORS
# ═══════════════════════════════════════════════════════════════════════════════

EMAIL_PATTERN = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)


def is_valid_email(email: str) -> bool:
    """Проверить email."""
    return bool(EMAIL_PATTERN.match(email.strip()))


# ═══════════════════════════════════════════════════════════════════════════════
# CURRENCY & AMOUNT VALIDATORS
# ═══════════════════════════════════════════════════════════════════════════════

SUPPORTED_CURRENCIES = {"USD", "CNY", "TMT", "EUR", "RUB", "GBP"}

# Паттерн суммы: "$1,500.50", "1500", "1 500.50"
AMOUNT_PATTERN = re.compile(
    r"^[\$€¥₽£]?\s*(\d{1,3}(?:[,\s]\d{3})*(?:\.\d{1,2})?)\s*"
    r"(USD|CNY|TMT|EUR|RUB|GBP|\$|€|¥)?$",
    re.IGNORECASE,
)


def is_valid_currency(currency: str) -> bool:
    """Проверить код валюты."""
    return currency.upper() in SUPPORTED_CURRENCIES


def is_valid_amount(amount: Union[str, float, int]) -> bool:
    """Проверить сумму (> 0)."""
    if isinstance(amount, (int, float)):
        return amount > 0
    if isinstance(amount, str):
        try:
            cleaned = re.sub(r"[\$€¥₽£,\s]", "", amount)
            return float(cleaned) > 0
        except (ValueError, TypeError):
            return False
    return False


def parse_amount(text: str) -> Optional[float]:
    """
    Извлечь числовую сумму из текста.

    parse_amount("$1,500.50") → 1500.50
    parse_amount("1500") → 1500.0
    """
    try:
        cleaned = re.sub(r"[^\d.]", "", text.replace(",", ""))
        return float(cleaned) if cleaned else None
    except (ValueError, TypeError):
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# DATE VALIDATORS
# ═══════════════════════════════════════════════════════════════════════════════

DATE_FORMATS = [
    "%Y-%m-%d",
    "%d.%m.%Y",
    "%d/%m/%Y",
    "%Y-%m-%d %H:%M",
    "%d.%m.%Y %H:%M",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%dT%H:%M:%S",
]


def is_valid_date(text: str) -> bool:
    """Проверить, является ли текст валидной датой."""
    return parse_date(text) is not None


def parse_date(text: str) -> Optional[datetime]:
    """
    Разобрать дату из текста.

    parse_date("25.12.2025") → datetime(2025, 12, 25)
    parse_date("2025-12-25 14:30") → datetime(2025, 12, 25, 14, 30)
    """
    text = text.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def is_future_date(dt: Union[date, datetime]) -> bool:
    """Проверить, что дата в будущем."""
    target = dt.date() if isinstance(dt, datetime) else dt
    return target > date.today()


def is_past_date(dt: Union[date, datetime]) -> bool:
    """Проверить, что дата в прошлом."""
    target = dt.date() if isinstance(dt, datetime) else dt
    return target < date.today()


# ═══════════════════════════════════════════════════════════════════════════════
# TRACKING NUMBER VALIDATORS
# ═══════════════════════════════════════════════════════════════════════════════

TRACKING_PATTERNS = {
    "sf_express": re.compile(r"^SF\d{12,15}$"),
    "ems": re.compile(r"^E[A-Z]\d{9}[A-Z]{2}$"),
    "ups": re.compile(r"^1Z[A-Z0-9]{16}$"),
    "fedex": re.compile(r"^\d{12,22}$"),
    "dhl": re.compile(r"^\d{10,11}$"),
    "china_post": re.compile(r"^[A-Z]{2}\d{9}CN$"),
    "yto": re.compile(r"^YT\d{13}$"),
    "zto": re.compile(r"^ZTO?\d{12,14}$"),
    "sto": re.compile(r"^STO?\d{12,14}$"),
}


def is_valid_tracking(number: str) -> bool:
    """Проверить, похож ли номер на трекинг."""
    number = number.strip().upper()
    return any(p.match(number) for p in TRACKING_PATTERNS.values())


def detect_carrier(number: str) -> Optional[str]:
    """Определить перевозчика по трекинг-номеру."""
    number = number.strip().upper()
    for carrier, pattern in TRACKING_PATTERNS.items():
        if pattern.match(number):
            return carrier
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# FILE VALIDATORS
# ═══════════════════════════════════════════════════════════════════════════════

ALLOWED_DOCUMENT_EXTENSIONS = {
    ".xlsx", ".xls", ".csv", ".docx", ".doc",
    ".pdf", ".txt", ".json", ".md",
}

ALLOWED_IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff",
}

ALLOWED_VOICE_EXTENSIONS = {
    ".ogg", ".mp3", ".wav", ".m4a", ".opus",
}

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


def is_valid_file_extension(
    filename: str,
    allowed: Optional[set[str]] = None,
) -> bool:
    """Проверить расширение файла."""
    if allowed is None:
        allowed = (
            ALLOWED_DOCUMENT_EXTENSIONS
            | ALLOWED_IMAGE_EXTENSIONS
            | ALLOWED_VOICE_EXTENSIONS
        )
    ext = os.path.splitext(filename)[1].lower()
    return ext in allowed


def is_document(filename: str) -> bool:
    """Это документ?"""
    return is_valid_file_extension(filename, ALLOWED_DOCUMENT_EXTENSIONS)


def is_image(filename: str) -> bool:
    """Это изображение?"""
    return is_valid_file_extension(filename, ALLOWED_IMAGE_EXTENSIONS)


def is_voice(filename: str) -> bool:
    """Это голосовое сообщение?"""
    return is_valid_file_extension(filename, ALLOWED_VOICE_EXTENSIONS)


def validate_file_size(
    file_path: str,
    max_size: int = MAX_FILE_SIZE,
) -> tuple[bool, str]:
    """
    Проверить размер файла.

    Returns:
        (is_valid, message)
    """
    if not os.path.exists(file_path):
        return False, "Файл не найден"

    size = os.path.getsize(file_path)
    if size > max_size:
        mb = size / (1024 * 1024)
        max_mb = max_size / (1024 * 1024)
        return False, f"Файл слишком большой: {mb:.1f} МБ (макс: {max_mb:.0f} МБ)"

    if size == 0:
        return False, "Файл пустой"

    return True, "OK"


# ═══════════════════════════════════════════════════════════════════════════════
# TEXT VALIDATORS
# ═══════════════════════════════════════════════════════════════════════════════

def is_not_empty(text: Optional[str]) -> bool:
    """Проверить, что текст непустой."""
    return bool(text and text.strip())


def validate_text_length(
    text: str,
    min_length: int = 1,
    max_length: int = 4096,
) -> tuple[bool, str]:
    """
    Валидировать длину текста.

    Returns:
        (is_valid, message)
    """
    if len(text) < min_length:
        return False, f"Текст слишком короткий (мин: {min_length})"
    if len(text) > max_length:
        return False, f"Текст слишком длинный (макс: {max_length})"
    return True, "OK"


def is_safe_filename(filename: str) -> bool:
    """
    Проверить безопасность имени файла.
    Нет path traversal, нет спецсимволов.
    """
    if not filename:
        return False
    # Запрещённые паттерны
    if ".." in filename or "/" in filename or "\\" in filename:
        return False
    # Только разрешённые символы
    return bool(
        re.match(r"^[a-zA-Z0-9а-яёА-ЯЁ\s_\-\.]+$", filename)
    )


# ═══════════════════════════════════════════════════════════════════════════════
# ORDER VALIDATORS
# ═══════════════════════════════════════════════════════════════════════════════

ORDER_NUMBER_PATTERN = re.compile(r"^ORD-\d{4,}$")


def is_valid_order_number(number: str) -> bool:
    """Проверить формат номера заказа (ORD-XXXX)."""
    return bool(ORDER_NUMBER_PATTERN.match(number.strip().upper()))


# ═══════════════════════════════════════════════════════════════════════════════
# COMPOSITE VALIDATOR
# ═══════════════════════════════════════════════════════════════════════════════

class ValidationResult:
    """Результат валидации."""

    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def to_dict(self) -> dict:
        return {
            "valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
        }

    def __repr__(self) -> str:
        return (
            f"ValidationResult(valid={self.is_valid}, "
            f"errors={len(self.errors)}, warnings={len(self.warnings)})"
        )


def validate_order_input(
    items_text: Optional[str] = None,
    file_path: Optional[str] = None,
) -> ValidationResult:
    """
    Комплексная валидация входных данных заказа.
    """
    result = ValidationResult()

    if not items_text and not file_path:
        result.add_error("Не указан текст заказа и не прикреплён файл")
        return result

    if items_text:
        valid, msg = validate_text_length(
            items_text, min_length=3, max_length=10000)
        if not valid:
            result.add_error(f"Текст: {msg}")

    if file_path:
        if not os.path.exists(file_path):
            result.add_error(f"Файл не найден: {file_path}")
        else:
            if not is_valid_file_extension(
                file_path,
                ALLOWED_DOCUMENT_EXTENSIONS | ALLOWED_IMAGE_EXTENSIONS,
            ):
                result.add_error(f"Неподдерживаемый формат: {file_path}")
            else:
                valid, msg = validate_file_size(file_path)
                if not valid:
                    result.add_error(f"Файл: {msg}")

    return result
