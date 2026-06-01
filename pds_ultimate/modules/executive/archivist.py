"""
PDS-Ultimate Archivist
=========================
Архивариус: стандартизация имён файлов, категоризация,
пакетное переименование, поиск по архиву.

По ТЗ §7.5:
- Все файлы переименовываются: 2026_02_07_Заказ_Балаклавы.pdf
- Автоматическая категоризация файлов
- Пакетное переименование директорий
- Поиск файлов по дате, типу, ключевым словам
- Ведение реестра всех файлов

Стандарт именования:
    YYYY_MM_DD_[Категория]_[Описание].[ext]
    Пример: 2026_02_07_Заказ_Балаклавы.pdf
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from pds_ultimate.config import (
    logger,
)

# ─── Data Models ─────────────────────────────────────────────────────────────


class FileCategory:
    """Категории файлов."""
    ORDER = "Заказ"
    INVOICE = "Инвойс"
    RECEIPT = "Чек"
    REPORT = "Отчёт"
    CONTRACT = "Контракт"
    LETTER = "Письмо"
    PHOTO = "Фото"
    DOCUMENT = "Документ"
    BACKUP = "Бэкап"
    ARCHIVE = "Архив"
    OTHER = "Файл"


# Ключевые слова для категоризации
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    FileCategory.ORDER: [
        "заказ", "order", "закупк", "покупк", "партия",
        "订单", "采购",
    ],
    FileCategory.INVOICE: [
        "инвойс", "invoice", "счёт", "счет", "bill",
        "发票",
    ],
    FileCategory.RECEIPT: [
        "чек", "receipt", "квитанц", "оплат",
        "收据",
    ],
    FileCategory.REPORT: [
        "отчёт", "отчет", "report", "статистик", "аналитик",
        "报告",
    ],
    FileCategory.CONTRACT: [
        "контракт", "договор", "contract", "соглашен",
        "合同",
    ],
    FileCategory.LETTER: [
        "письмо", "letter", "обращен",
        "信函",
    ],
    FileCategory.PHOTO: [
        "фото", "photo", "скрин", "screenshot", "снимок",
    ],
    FileCategory.BACKUP: [
        "бэкап", "backup", "резервн",
    ],
    FileCategory.ARCHIVE: [
        "архив", "archive", "история",
    ],
}

# Расширения → типы
EXTENSION_CATEGORIES = {
    ".xlsx": FileCategory.DOCUMENT,
    ".xls": FileCategory.DOCUMENT,
    ".docx": FileCategory.DOCUMENT,
    ".doc": FileCategory.DOCUMENT,
    ".pdf": FileCategory.DOCUMENT,
    ".csv": FileCategory.DOCUMENT,
    ".json": FileCategory.DOCUMENT,
    ".txt": FileCategory.DOCUMENT,
    ".md": FileCategory.DOCUMENT,
    ".jpg": FileCategory.PHOTO,
    ".jpeg": FileCategory.PHOTO,
    ".png": FileCategory.PHOTO,
    ".gif": FileCategory.PHOTO,
    ".webp": FileCategory.PHOTO,
    ".zip": FileCategory.ARCHIVE,
    ".tar": FileCategory.ARCHIVE,
    ".gz": FileCategory.ARCHIVE,
    ".rar": FileCategory.ARCHIVE,
    ".bak": FileCategory.BACKUP,
    ".db": FileCategory.BACKUP,
}


@dataclass
class FileRecord:
    """Запись файла в реестре архивариуса."""
    original_name: str
    standardized_name: str
    path: str
    category: str
    size_bytes: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    modified_at: Optional[datetime] = None
    tags: list[str] = field(default_factory=list)

    @property
    def size_kb(self) -> float:
        return self.size_bytes / 1024

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)

    def to_dict(self) -> dict:
        return {
            "original": self.original_name,
            "standardized": self.standardized_name,
            "path": self.path,
            "category": self.category,
            "size_kb": round(self.size_kb, 1),
            "created": self.created_at.isoformat(),
            "tags": self.tags,
        }


@dataclass
class RenameResult:
    """Результат операции переименования."""
    old_name: str
    new_name: str
    old_path: str
    new_path: str
    success: bool = True
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "old": self.old_name,
            "new": self.new_name,
            "success": self.success,
            "error": self.error,
        }


@dataclass
class BatchRenameResult:
    """Результат пакетного переименования."""
    results: list[RenameResult] = field(default_factory=list)
    success_count: int = 0
    error_count: int = 0

    def to_dict(self) -> dict:
        return {
            "total": len(self.results),
            "success": self.success_count,
            "errors": self.error_count,
            "results": [r.to_dict() for r in self.results],
        }


# ─── Archivist Service ───────────────────────────────────────────────────────

class ArchivistService:
    """
    Архивариус: стандартизация, категоризация, поиск файлов.

    Архитектура:
    - Именование по стандарту: YYYY_MM_DD_Категория_Описание.ext
    - Авто-категоризация по ключевым словам и расширению
    - Пакетное переименование директории
    - Реестр файлов (in-memory + DB)
    - Поиск по имени, дате, категории, тегам

    Использование:
        name = archivist.standardize("invoice.pdf", "Заказ Балаклавы")
        result = archivist.rename_file("/path/to/file.pdf", context="Заказ 5")
        batch = archivist.rename_directory("/path/to/dir")
    """

    # Pattern для уже стандартизованного имени
    STANDARD_PATTERN = re.compile(
        r'^\d{4}_\d{2}_\d{2}_[А-Яа-яA-Za-z0-9_]+\.\w+$'
    )

    # Symbols to clean from filenames
    UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

    def __init__(self):
        self._registry: dict[str, FileRecord] = {}
        self._rename_count = 0

    # ═══════════════════════════════════════════════════════════════════════
    # Standardization
    # ═══════════════════════════════════════════════════════════════════════

    def standardize(
        self,
        original_name: str,
        context: str = "",
        date: Optional[datetime] = None,
        category: Optional[str] = None,
    ) -> str:
        """
        Стандартизировать имя файла.

        Input:  "invoice.pdf", context="Заказ Балаклавы"
        Output: "2026_02_07_Заказ_Балаклавы.pdf"
        """
        if date is None:
            date = datetime.now()

        date_prefix = date.strftime("%Y_%m_%d")
        ext = Path(original_name).suffix.lower()
        stem = Path(original_name).stem

        # Определить категорию
        if not category:
            category = self.detect_category(
                original_name + " " + context
            )

        # Описание: из context или из stem
        if context:
            description = self._clean_name(context)
        else:
            description = self._clean_name(stem)

        # Обрезаем длинные имена
        max_desc_len = 80
        if len(description) > max_desc_len:
            description = description[:max_desc_len]

        # Убираем дублирование даты если уже есть
        if description.startswith(date_prefix):
            description = description[len(date_prefix):].lstrip("_")

        # Собираем
        parts = [date_prefix]
        if category and category != FileCategory.OTHER:
            parts.append(self._clean_name(category))
        if description:
            parts.append(description)

        name = "_".join(parts) + ext
        return name

    def is_standardized(self, filename: str) -> bool:
        """Проверить, соответствует ли имя стандарту."""
        return bool(self.STANDARD_PATTERN.match(filename))

    # ═══════════════════════════════════════════════════════════════════════
    # Category Detection
    # ═══════════════════════════════════════════════════════════════════════

    def detect_category(self, text: str) -> str:
        """Определить категорию файла по названию и контексту."""
        text_lower = text.lower()

        # По ключевым словам
        scores: dict[str, int] = {}
        for cat, keywords in CATEGORY_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[cat] = score

        if scores:
            return max(scores, key=scores.get)

        # По расширению
        ext = Path(text).suffix.lower()
        if ext in EXTENSION_CATEGORIES:
            return EXTENSION_CATEGORIES[ext]

        return FileCategory.OTHER

    def auto_tag(self, filename: str, content_hint: str = "") -> list[str]:
        """Авто-тегирование файла."""
        tags = []
        text = (filename + " " + content_hint).lower()

        # Тип
        ext = Path(filename).suffix.lower()
        if ext in (".xlsx", ".xls", ".csv"):
            tags.append("таблица")
        elif ext in (".docx", ".doc"):
            tags.append("документ")
        elif ext == ".pdf":
            tags.append("pdf")
        elif ext in (".jpg", ".jpeg", ".png", ".gif"):
            tags.append("изображение")

        # Контент
        if any(w in text for w in ["заказ", "order"]):
            tags.append("заказ")
        if any(w in text for w in ["финанс", "деньг", "расход", "доход"]):
            tags.append("финансы")
        if any(w in text for w in ["архив", "archive", "история"]):
            tags.append("архив")

        return tags

    # ═══════════════════════════════════════════════════════════════════════
    # File Operations
    # ═══════════════════════════════════════════════════════════════════════

    def rename_file(
        self,
        filepath: str,
        context: str = "",
        category: Optional[str] = None,
        move_to: Optional[str] = None,
    ) -> RenameResult:
        """
        Переименовать файл по стандарту.

        Args:
            filepath: Путь к файлу
            context: Контекст для именования
            category: Категория (авто-определение если None)
            move_to: Переместить в директорию (optional)
        """
        path = Path(filepath)
        if not path.exists():
            return RenameResult(
                old_name=path.name,
                new_name="",
                old_path=filepath,
                new_path="",
                success=False,
                error="Файл не найден",
            )

        old_name = path.name

        # Уже стандартизован?
        if self.is_standardized(old_name) and not context:
            return RenameResult(
                old_name=old_name,
                new_name=old_name,
                old_path=filepath,
                new_path=filepath,
                success=True,
            )

        new_name = self.standardize(old_name, context, category=category)

        # Целевая директория
        target_dir = Path(move_to) if move_to else path.parent
        new_path = target_dir / new_name

        # Разрешение конфликтов имён
        counter = 1
        while new_path.exists() and new_path != path:
            stem = new_path.stem
            ext = new_path.suffix
            new_path = target_dir / f"{stem}_{counter}{ext}"
            new_name = new_path.name
            counter += 1

        try:
            if move_to:
                target_dir.mkdir(parents=True, exist_ok=True)

            if path != new_path:
                shutil.move(str(path), str(new_path))

            self._rename_count += 1

            # Регистрация в реестре
            self._register(old_name, new_name, str(new_path), category)

            logger.info(
                f"[Archivist] Renamed: {old_name} → {new_name}"
            )

            return RenameResult(
                old_name=old_name,
                new_name=new_name,
                old_path=filepath,
                new_path=str(new_path),
            )

        except Exception as e:
            return RenameResult(
                old_name=old_name,
                new_name=new_name,
                old_path=filepath,
                new_path=str(new_path),
                success=False,
                error=str(e),
            )

    def rename_directory(
        self,
        dirpath: str,
        recursive: bool = False,
        context: str = "",
    ) -> BatchRenameResult:
        """
        Пакетное переименование всех файлов в директории.

        Args:
            dirpath: Путь к директории
            recursive: Включая вложенные
            context: Общий контекст для именования
        """
        result = BatchRenameResult()
        dir_path = Path(dirpath)

        if not dir_path.is_dir():
            return result

        pattern = "**/*" if recursive else "*"
        files = [
            f for f in dir_path.glob(pattern)
            if f.is_file() and not f.name.startswith(".")
        ]

        for filepath in sorted(files):
            rename_result = self.rename_file(
                str(filepath), context=context
            )
            result.results.append(rename_result)

            if rename_result.success:
                result.success_count += 1
            else:
                result.error_count += 1

        return result

    # ═══════════════════════════════════════════════════════════════════════
    # Search
    # ═══════════════════════════════════════════════════════════════════════

    def search(
        self,
        query: str = "",
        category: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        tags: Optional[list[str]] = None,
        directory: Optional[str] = None,
    ) -> list[FileRecord]:
        """Поиск файлов в реестре и на диске."""
        results = []

        # Поиск в реестре
        for record in self._registry.values():
            if not self._matches_filter(
                record, query, category, date_from, date_to, tags
            ):
                continue
            results.append(record)

        # Поиск на диске (если указана директория)
        if directory:
            disk_results = self._search_disk(
                directory, query, category, date_from, date_to
            )
            results.extend(disk_results)

        # Сортировка по дате (новые первые)
        results.sort(key=lambda r: r.created_at, reverse=True)

        return results

    def search_by_date(
        self,
        date: datetime,
        directory: Optional[str] = None,
    ) -> list[FileRecord]:
        """Поиск файлов по дате."""
        date_str = date.strftime("%Y_%m_%d")
        return self.search(query=date_str, directory=directory)

    # ═══════════════════════════════════════════════════════════════════════
    # Formatting
    # ═══════════════════════════════════════════════════════════════════════

    def format_rename_result(self, result: RenameResult) -> str:
        """Форматировать результат переименования."""
        if result.success:
            return f"✅ {result.old_name} → {result.new_name}"
        return f"❌ {result.old_name}: {result.error}"

    def format_batch_result(self, result: BatchRenameResult) -> str:
        """Форматировать результат пакетного переименования."""
        lines = [
            f"📁 Переименование: {result.success_count} ✅, "
            f"{result.error_count} ❌\n"
        ]

        for r in result.results[:20]:  # Максимум 20 записей
            lines.append(f"  {self.format_rename_result(r)}")

        if len(result.results) > 20:
            lines.append(f"\n  ... и ещё {len(result.results) - 20}")

        return "\n".join(lines)

    def format_search_results(self, records: list[FileRecord]) -> str:
        """Форматировать результаты поиска."""
        if not records:
            return "🔍 Файлы не найдены."

        lines = [f"🔍 Найдено файлов: {len(records)}\n"]

        for i, record in enumerate(records[:20], 1):
            size_str = f"{record.size_kb:.1f} КБ" if record.size_kb else ""
            lines.append(
                f"  {i}. 📄 {record.standardized_name} "
                f"[{record.category}] {size_str}"
            )

        if len(records) > 20:
            lines.append(f"\n  ... и ещё {len(records) - 20}")

        return "\n".join(lines)

    def get_stats(self) -> dict:
        """Статистика архивариуса."""
        return {
            "total_registered": len(self._registry),
            "total_renames": self._rename_count,
            "categories": self._count_categories(),
        }

    # ═══════════════════════════════════════════════════════════════════════
    # Internal
    # ═══════════════════════════════════════════════════════════════════════

    def _clean_name(self, name: str) -> str:
        """Очистить строку для использования в имени файла."""
        # Убираем расширение если есть
        if "." in name:
            stem = Path(name).stem
            if len(stem) > 3:  # не ".pdf" а "file.pdf"
                name = stem

        # Заменяем пробелы и спецсимволы
        name = self.UNSAFE_CHARS.sub("", name)
        name = name.replace(" ", "_").replace("-", "_")
        name = re.sub(r'_+', '_', name)  # multiple underscores → one
        name = name.strip("_")

        return name

    def _register(
        self,
        original: str,
        standardized: str,
        path: str,
        category: Optional[str],
    ) -> None:
        """Зарегистрировать файл в реестре."""
        size = 0
        if os.path.exists(path):
            size = os.path.getsize(path)

        record = FileRecord(
            original_name=original,
            standardized_name=standardized,
            path=path,
            category=category or self.detect_category(original),
            size_bytes=size,
            tags=self.auto_tag(standardized),
        )

        self._registry[path] = record

    def _matches_filter(
        self,
        record: FileRecord,
        query: str,
        category: Optional[str],
        date_from: Optional[datetime],
        date_to: Optional[datetime],
        tags: Optional[list[str]],
    ) -> bool:
        """Проверить, подходит ли файл под фильтр."""
        if query:
            q_lower = query.lower()
            searchable = (
                record.original_name.lower() + " " +
                record.standardized_name.lower() + " " +
                record.category.lower()
            )
            if q_lower not in searchable:
                return False

        if category and record.category != category:
            return False

        if date_from and record.created_at < date_from:
            return False

        if date_to and record.created_at > date_to:
            return False

        if tags:
            if not any(t in record.tags for t in tags):
                return False

        return True

    def _search_disk(
        self,
        directory: str,
        query: str,
        category: Optional[str],
        date_from: Optional[datetime],
        date_to: Optional[datetime],
    ) -> list[FileRecord]:
        """Поиск файлов на диске."""
        results = []
        dir_path = Path(directory)

        if not dir_path.is_dir():
            return results

        for filepath in dir_path.rglob("*"):
            if not filepath.is_file():
                continue
            if filepath.name.startswith("."):
                continue

            name = filepath.name.lower()

            # Query filter
            if query and query.lower() not in name:
                continue

            # Category filter
            detected_cat = self.detect_category(filepath.name)
            if category and detected_cat != category:
                continue

            # Date filter
            stat = filepath.stat()
            file_date = datetime.fromtimestamp(stat.st_mtime)

            if date_from and file_date < date_from:
                continue
            if date_to and file_date > date_to:
                continue

            record = FileRecord(
                original_name=filepath.name,
                standardized_name=filepath.name,
                path=str(filepath),
                category=detected_cat,
                size_bytes=stat.st_size,
                created_at=file_date,
            )
            results.append(record)

        return results

    def _count_categories(self) -> dict[str, int]:
        """Подсчёт файлов по категориям."""
        counts: dict[str, int] = {}
        for record in self._registry.values():
            counts[record.category] = counts.get(record.category, 0) + 1
        return counts


# ─── Глобальный экземпляр ────────────────────────────────────────────────────

archivist = ArchivistService()
