"""
PDS-Ultimate Helpers
======================
Общие утилиты-хелперы для всех модулей.

- Хеширование и ID-генерация
- Размер файлов
- Retry-логика
- Chunk-обработка
- Safe JSON
- Timing
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
from datetime import datetime
from functools import wraps
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Iterable,
    TypeVar,
)

from pds_ultimate.config import logger

T = TypeVar("T")


# ═══════════════════════════════════════════════════════════════════════════════
# ID GENERATION
# ═══════════════════════════════════════════════════════════════════════════════

def generate_id(prefix: str = "") -> str:
    """
    Генерировать уникальный ID.

    generate_id("order") → "order_a1b2c3d4"
    generate_id() → "a1b2c3d4e5f6"
    """
    uid = uuid.uuid4().hex[:12]
    if prefix:
        return f"{prefix}_{uid}"
    return uid


def generate_short_id(length: int = 8) -> str:
    """Короткий ID."""
    return uuid.uuid4().hex[:length]


# ═══════════════════════════════════════════════════════════════════════════════
# HASHING
# ═══════════════════════════════════════════════════════════════════════════════

def hash_text(text: str) -> str:
    """SHA256 хеш текста."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_file(file_path: str) -> str:
    """SHA256 хеш файла."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def quick_hash(text: str, length: int = 8) -> str:
    """Быстрый короткий хеш."""
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:length]


# ═══════════════════════════════════════════════════════════════════════════════
# FILE SIZE
# ═══════════════════════════════════════════════════════════════════════════════

def format_file_size(size_bytes: int) -> str:
    """
    Человеко-читаемый размер файла.

    format_file_size(1536) → "1.5 КБ"
    format_file_size(1048576) → "1.0 МБ"
    """
    if size_bytes < 1024:
        return f"{size_bytes} Б"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} КБ"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} МБ"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} ГБ"


def get_file_size(file_path: str) -> int:
    """Размер файла в байтах."""
    try:
        return os.path.getsize(file_path)
    except OSError:
        return 0


# ═══════════════════════════════════════════════════════════════════════════════
# RETRY LOGIC
# ═══════════════════════════════════════════════════════════════════════════════

async def async_retry(
    func: Callable,
    *args: Any,
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
    **kwargs: Any,
) -> Any:
    """
    Повторить async-вызов при ошибке.

    result = await async_retry(some_api_call, url, max_retries=3)
    """
    last_error = None
    current_delay = delay

    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except exceptions as e:
            last_error = e
            if attempt < max_retries:
                logger.warning(
                    f"Retry {attempt + 1}/{max_retries}: {func.__name__} "
                    f"failed: {e}. Waiting {current_delay}s..."
                )
                await asyncio.sleep(current_delay)
                current_delay *= backoff
            else:
                raise last_error


def retry_decorator(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
):
    """
    Декоратор для retry async-функций.

    @retry_decorator(max_retries=3)
    async def fetch_data(url):
        ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await async_retry(
                func, *args,
                max_retries=max_retries,
                delay=delay,
                backoff=backoff,
                exceptions=exceptions,
                **kwargs,
            )
        return wrapper
    return decorator


# ═══════════════════════════════════════════════════════════════════════════════
# CHUNKING
# ═══════════════════════════════════════════════════════════════════════════════

def chunks(iterable: Iterable[T], size: int) -> list[list[T]]:
    """
    Разбить итерируемое на чанки.

    chunks([1,2,3,4,5], 2) → [[1,2], [3,4], [5]]
    """
    items = list(iterable)
    return [items[i: i + size] for i in range(0, len(items), size)]


async def async_chunks(
    items: list[T],
    size: int,
) -> AsyncIterator[list[T]]:
    """Async генератор чанков."""
    for i in range(0, len(items), size):
        yield items[i: i + size]


# ═══════════════════════════════════════════════════════════════════════════════
# SAFE JSON
# ═══════════════════════════════════════════════════════════════════════════════

def safe_json_loads(text: str, default: Any = None) -> Any:
    """
    Безопасный json.loads.

    safe_json_loads('{"a": 1}') → {"a": 1}
    safe_json_loads('broken') → None
    """
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default


def safe_json_dumps(
    obj: Any,
    ensure_ascii: bool = False,
    indent: int = 2,
) -> str:
    """Безопасный json.dumps с fallback."""
    try:
        return json.dumps(
            obj, ensure_ascii=ensure_ascii,
            indent=indent, default=str,
        )
    except (TypeError, ValueError):
        return str(obj)


# ═══════════════════════════════════════════════════════════════════════════════
# TIMING
# ═══════════════════════════════════════════════════════════════════════════════

class Timer:
    """
    Контекстный менеджер для замера времени.

    with Timer("operation") as t:
        do_work()
    print(t.elapsed)  # 1.234
    """

    def __init__(self, label: str = ""):
        self.label = label
        self.start_time: float = 0
        self.end_time: float = 0
        self.elapsed: float = 0

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.end_time = time.perf_counter()
        self.elapsed = self.end_time - self.start_time
        if self.label:
            logger.debug(f"⏱️ {self.label}: {self.elapsed:.3f}s")

    @property
    def elapsed_ms(self) -> float:
        return self.elapsed * 1000


class AsyncTimer:
    """Async контекстный менеджер для замера."""

    def __init__(self, label: str = ""):
        self.label = label
        self.start_time: float = 0
        self.elapsed: float = 0

    async def __aenter__(self):
        self.start_time = time.perf_counter()
        return self

    async def __aexit__(self, *args):
        self.elapsed = time.perf_counter() - self.start_time
        if self.label:
            logger.debug(f"⏱️ {self.label}: {self.elapsed:.3f}s")

    @property
    def elapsed_ms(self) -> float:
        return self.elapsed * 1000


# ═══════════════════════════════════════════════════════════════════════════════
# MISC
# ═══════════════════════════════════════════════════════════════════════════════

def clamp(value: float, min_val: float, max_val: float) -> float:
    """Ограничить значение в диапазоне."""
    return max(min_val, min(max_val, value))


def first_non_none(*values: Any) -> Any:
    """Первое не-None значение."""
    for v in values:
        if v is not None:
            return v
    return None


def now_iso() -> str:
    """Текущее время в ISO формате."""
    return datetime.now().isoformat()


def safe_int(value: Any, default: int = 0) -> int:
    """Безопасное преобразование в int."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    """Безопасное преобразование в float."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def flatten(nested: list[list[T]]) -> list[T]:
    """Развернуть вложенные списки."""
    return [item for sublist in nested for item in sublist]


def deduplicate(items: list[T]) -> list[T]:
    """Убрать дубликаты, сохраняя порядок."""
    seen = set()
    result = []
    for item in items:
        key = str(item)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result
