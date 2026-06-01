"""
Тесты кросс-ссылок и целостности кодовой базы.
Проверяем что все enum-ы, модели и конфиги согласованы.
"""

from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent


class TestEnumConsistency:
    """Все ссылки на enum-ы корректны."""

    def test_profit_expenses_plural(self):
        """PROFIT_EXPENSES (множественное) используется везде."""
        files_to_check = [
            "bot/handlers/universal.py",
            "modules/logistics/order_manager.py",
            "modules/finance/master_finance.py",
            "modules/finance/sync_engine.py",
            "modules/executive/morning_brief.py",
        ]

        for rel_path in files_to_check:
            fpath = BASE / rel_path
            if fpath.exists():
                content = fpath.read_text(encoding="utf-8")
                # Должен быть PROFIT_EXPENSES (plural)
                if "PROFIT_EXPENSE" in content:
                    # Проверяем что нет PROFIT_EXPENSE без S
                    lines = content.split("\n")
                    for i, line in enumerate(lines, 1):
                        if "PROFIT_EXPENSE" in line and "PROFIT_EXPENSES" not in line:
                            pytest.fail(
                                f"{rel_path}:{i} — "
                                f"PROFIT_EXPENSE без S: {line.strip()}"
                            )

    def test_config_telegram_not_telegram_bot(self):
        """config.telegram (не config.telegram_bot) в setup.py."""
        setup_path = BASE / "bot" / "setup.py"
        if setup_path.exists():
            content = setup_path.read_text(encoding="utf-8")
            assert "config.telegram_bot" not in content, \
                "setup.py использует config.telegram_bot вместо config.telegram"
            assert "config.telegram" in content

    def test_reminder_field_message_not_text(self):
        """Reminder.message (не .text) в scheduler.py."""
        scheduler_path = BASE / "core" / "scheduler.py"
        if scheduler_path.exists():
            content = scheduler_path.read_text(encoding="utf-8")
            lines = content.split("\n")
            for i, line in enumerate(lines, 1):
                if "rem.text" in line:
                    pytest.fail(
                        f"scheduler.py:{i} — rem.text вместо rem.message: "
                        f"{line.strip()}"
                    )

    def test_no_google_calendar_refs(self):
        """Нет ссылок на Google Calendar (удалён по ТЗ)."""
        for py_file in BASE.rglob("*.py"):
            if "tests" in str(py_file):
                continue
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            if "google_event_id" in content.lower():
                rel = py_file.relative_to(BASE)
                pytest.fail(
                    f"{rel} содержит ссылку на google_event_id"
                )

    def test_calendar_reminder_30(self):
        """CalendarEvent.reminder_minutes default=30."""
        from pds_ultimate.core.database import CalendarEvent
        event = CalendarEvent.__table__
        col = event.c.get("reminder_minutes")
        if col is not None and col.default is not None:
            default = col.default.arg
            assert default == 30, f"reminder_minutes default={default}, ожидалось 30"


class TestSyntaxAll:
    """Все .py файлы проходят синтаксическую проверку."""

    def test_all_files_syntax(self):
        """Каждый .py файл компилируется без ошибок."""
        errors = []
        for py_file in BASE.rglob("*.py"):
            try:
                with open(py_file, "r", encoding="utf-8") as f:
                    source = f.read()
                compile(source, str(py_file), "exec")
            except SyntaxError as e:
                rel = py_file.relative_to(BASE)
                errors.append(f"{rel}:{e.lineno}: {e.msg}")

        if errors:
            pytest.fail(
                "Синтаксические ошибки:\n" + "\n".join(errors)
            )

    def test_file_count(self):
        """В проекте 40+ Python файлов."""
        count = sum(1 for _ in BASE.rglob("*.py"))
        assert count >= 40, f"Найдено {count} файлов, ожидалось ≥40"


class TestModuleExports:
    """Все __init__.py содержат правильные экспорты."""

    def test_integrations_init(self):
        """integrations/__init__.py экспортирует все клиенты."""
        from pds_ultimate.integrations import __all__

        expected = {
            "WhatsAppClient", "wa_client",
            "GmailClient", "gmail_client",
            "TelethonClient", "telethon_client",
            "ExchangeRateService", "exchange_service",
            "GoogleCalendarService", "google_calendar",
        }
        assert expected == set(__all__)

    def test_core_init(self):
        """core/__init__.py существует."""
        init_path = BASE / "core" / "__init__.py"
        assert init_path.exists()

    def test_bot_init(self):
        """bot/__init__.py существует."""
        init_path = BASE / "bot" / "__init__.py"
        assert init_path.exists()
