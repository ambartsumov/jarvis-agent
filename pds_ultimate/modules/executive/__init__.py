"""
Executive Module
- MorningBrief: Утренний брифинг + 3-дневный отчёт + «что добавить/убрать?»
- BackupManager: Ежесуточный бэкап
- SecurityManager: Кодовое слово, экстренное удаление
- ReceiptScanner: Сканирование чеков и учёт расходов
- TranslatorService: Многоязычный перевод с бизнес-глоссарием
- ArchivistService: Автоименование, организация, поиск файлов
"""

from pds_ultimate.modules.executive.archivist import ArchivistService, archivist
from pds_ultimate.modules.executive.backup_security import (
    BackupManager,
    SecurityManager,
)
from pds_ultimate.modules.executive.morning_brief import MorningBrief
from pds_ultimate.modules.executive.receipt_scanner import (
    ReceiptScanner,
    receipt_scanner,
)
from pds_ultimate.modules.executive.translator import (
    TranslatorService,
    translator,
)

__all__ = [
    "MorningBrief",
    "BackupManager",
    "SecurityManager",
    "ReceiptScanner",
    "receipt_scanner",
    "TranslatorService",
    "translator",
    "ArchivistService",
    "archivist",
]
