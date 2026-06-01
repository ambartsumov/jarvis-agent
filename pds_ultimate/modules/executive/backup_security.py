"""
PDS-Ultimate Backup Manager
===============================
Ежесуточные бэкапы + экстренное удаление.

По ТЗ:
- Ежесуточный бэкап в 03:00
- Security Mode: кодовое слово → удаление финансовых данных
- Бэкап: local или email (на вторую почту)
"""

from __future__ import annotations

import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from pds_ultimate.config import (
    ALL_ORDERS_ARCHIVE_PATH,
    BACKUPS_DIR,
    DATA_DIR,
    DATABASE_PATH,
    MASTER_FINANCE_PATH,
    config,
    logger,
)


class BackupManager:
    """
    Бэкап-менеджер: ежесуточные бэкапы, восстановление.
    """

    def __init__(self, db_session_factory):
        self._session_factory = db_session_factory

    async def create_backup(self) -> dict:
        """
        Создать полный бэкап: БД + Excel-файлы → ZIP.
        """
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"pds_backup_{timestamp}.zip"
            backup_path = BACKUPS_DIR / backup_name

            # Убедиться что папка существует
            BACKUPS_DIR.mkdir(parents=True, exist_ok=True)

            files_to_backup = []

            # БД
            if DATABASE_PATH.exists():
                files_to_backup.append(
                    (str(DATABASE_PATH), "database/pds_ultimate.db")
                )

            # Master Finance
            if MASTER_FINANCE_PATH.exists():
                files_to_backup.append(
                    (str(MASTER_FINANCE_PATH), "finance/Master_Finance.xlsx")
                )

            # Archive
            if ALL_ORDERS_ARCHIVE_PATH.exists():
                files_to_backup.append(
                    (str(ALL_ORDERS_ARCHIVE_PATH),
                     "finance/All_Orders_Archive.xlsx")
                )

            # User files
            from pds_ultimate.config import USER_FILES_DIR
            if USER_FILES_DIR.exists():
                for f in USER_FILES_DIR.iterdir():
                    if f.is_file():
                        files_to_backup.append(
                            (str(f), f"user_files/{f.name}")
                        )

            if not files_to_backup:
                return {"error": "Нет файлов для бэкапа"}

            # Создание ZIP
            with zipfile.ZipFile(
                str(backup_path), "w", zipfile.ZIP_DEFLATED
            ) as zf:
                for src, arcname in files_to_backup:
                    zf.write(src, arcname)

            size = backup_path.stat().st_size
            size_mb = size / (1024 * 1024)

            logger.info(
                f"Backup created: {backup_name} ({size_mb:.1f} MB, "
                f"{len(files_to_backup)} files)"
            )

            # Очистка старых бэкапов (оставляем последние 30)
            await self._cleanup_old_backups(keep=30)

            result = {
                "backup_file": str(backup_path),
                "size_mb": round(size_mb, 2),
                "files_count": len(files_to_backup),
                "timestamp": timestamp,
            }

            # Отправка на email (если настроено)
            if config.security.backup_target == "email":
                email_result = await self._send_backup_email(backup_path)
                result["email_sent"] = email_result

            return result

        except Exception as e:
            logger.error(f"Backup failed: {e}")
            return {"error": str(e)}

    async def list_backups(self) -> list[dict]:
        """Список всех бэкапов."""
        if not BACKUPS_DIR.exists():
            return []

        backups = []
        for f in sorted(BACKUPS_DIR.iterdir(), reverse=True):
            if f.suffix == ".zip" and f.name.startswith("pds_backup_"):
                size_mb = f.stat().st_size / (1024 * 1024)
                backups.append({
                    "name": f.name,
                    "path": str(f),
                    "size_mb": round(size_mb, 2),
                    "created": datetime.fromtimestamp(
                        f.stat().st_mtime
                    ).isoformat(),
                })

        return backups

    async def restore_from_backup(self, backup_path: str) -> dict:
        """Восстановить из бэкапа."""
        if not os.path.exists(backup_path):
            return {"error": "Файл бэкапа не найден"}

        try:
            restore_dir = DATA_DIR / "restore_temp"
            restore_dir.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(backup_path, "r") as zf:
                zf.extractall(str(restore_dir))

            # Восстановление БД
            db_backup = restore_dir / "database" / "pds_ultimate.db"
            if db_backup.exists():
                shutil.copy2(str(db_backup), str(DATABASE_PATH))

            # Восстановление Excel
            finance_backup = restore_dir / "finance" / "Master_Finance.xlsx"
            if finance_backup.exists():
                shutil.copy2(str(finance_backup), str(MASTER_FINANCE_PATH))

            archive_backup = restore_dir / "finance" / "All_Orders_Archive.xlsx"
            if archive_backup.exists():
                shutil.copy2(str(archive_backup), str(ALL_ORDERS_ARCHIVE_PATH))

            # Очистка
            shutil.rmtree(str(restore_dir), ignore_errors=True)

            logger.info(f"Restored from backup: {backup_path}")
            return {"status": "ok", "restored_from": backup_path}

        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return {"error": str(e)}

    def format_backup_result(self, result: dict) -> str:
        """Форматирование результата бэкапа."""
        if "error" in result:
            return f"❌ Ошибка бэкапа: {result['error']}"

        return (
            f"💾 Бэкап создан:\n"
            f"  📦 Файл: {result['backup_file']}\n"
            f"  📐 Размер: {result['size_mb']} МБ\n"
            f"  📋 Файлов: {result['files_count']}"
        )

    # ═══════════════════════════════════════════════════════════════════════
    # Internal
    # ═══════════════════════════════════════════════════════════════════════

    async def _cleanup_old_backups(self, keep: int = 30) -> None:
        """Удалить старые бэкапы, оставить последние N."""
        if not BACKUPS_DIR.exists():
            return

        backups = sorted(
            [f for f in BACKUPS_DIR.iterdir() if f.suffix == ".zip"],
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )

        for old_backup in backups[keep:]:
            try:
                old_backup.unlink()
                logger.info(f"Old backup deleted: {old_backup.name}")
            except OSError:
                pass

    async def _send_backup_email(self, backup_path: Path) -> bool:
        """Отправить бэкап на email."""
        if not config.security.backup_email:
            return False

        # Реализация отправки через Gmail API (если настроен)
        # TODO: интеграция с Gmail
        logger.info(
            f"Backup email would be sent to: {config.security.backup_email}"
        )
        return False


# ═══════════════════════════════════════════════════════════════════════════
# Security Manager
# ═══════════════════════════════════════════════════════════════════════════

class SecurityManager:
    """
    Security Mode по ТЗ:
    - Кодовое слово → мгновенное удаление финансовых данных
    - Перед удалением: бэкап на email (если настроено)
    """

    def __init__(self, db_session_factory):
        self._session_factory = db_session_factory
        self._backup_manager = BackupManager(db_session_factory)

    async def emergency_wipe(self, code: str) -> dict:
        """
        Экстренное удаление финансовых данных.
        Требует правильного кодового слова.
        """
        expected = config.security.emergency_code
        if not expected:
            return {"error": "Кодовое слово не настроено"}

        if code != expected:
            logger.warning("Security: wrong emergency code attempted")
            return {"error": "Неверное кодовое слово"}

        logger.warning("SECURITY: Emergency wipe initiated!")

        # 1. Создать бэкап перед удалением
        backup_result = await self._backup_manager.create_backup()

        # 2. Удалить финансовые данные из БД
        from pds_ultimate.core.database import (
            ArchivedOrderItem,
            FinanceSummary,
            Transaction,
        )

        with self._session_factory() as session:
            deleted_transactions = session.query(Transaction).delete()
            deleted_summaries = session.query(FinanceSummary).delete()
            deleted_archive = session.query(ArchivedOrderItem).delete()
            session.commit()

        # 3. Удалить финансовые файлы
        deleted_files = []

        if MASTER_FINANCE_PATH.exists():
            os.remove(str(MASTER_FINANCE_PATH))
            deleted_files.append("Master_Finance.xlsx")

        if ALL_ORDERS_ARCHIVE_PATH.exists():
            os.remove(str(ALL_ORDERS_ARCHIVE_PATH))
            deleted_files.append("All_Orders_Archive.xlsx")

        logger.warning(
            f"SECURITY: Wiped {deleted_transactions} transactions, "
            f"{deleted_summaries} summaries, "
            f"{deleted_archive} archive items, "
            f"{len(deleted_files)} files"
        )

        return {
            "status": "wiped",
            "backup": backup_result,
            "deleted_transactions": deleted_transactions,
            "deleted_summaries": deleted_summaries,
            "deleted_archive_items": deleted_archive,
            "deleted_files": deleted_files,
        }

    def check_code(self, code: str) -> bool:
        """Проверить кодовое слово (без выполнения)."""
        return code == config.security.emergency_code
