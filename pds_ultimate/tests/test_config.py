"""
Тесты конфигурации — config.py
"""


import pytest


class TestConfigValidation:
    """Тесты валидации конфигурации."""

    def test_config_loads(self, test_config):
        """Конфигурация загружается без ошибок."""
        assert test_config is not None
        assert test_config.telegram is not None
        assert test_config.deepseek is not None

    def test_telegram_config(self, test_config):
        """Telegram конфиг заполнен из env."""
        assert test_config.telegram.token == "test:BOT_TOKEN_123456"
        assert test_config.telegram.owner_id == 999999999
        assert test_config.telegram.parse_mode == "HTML"

    def test_deepseek_config(self, test_config):
        """DeepSeek конфиг заполнен."""
        assert test_config.deepseek.api_key == "test_deepseek_key"
        assert test_config.deepseek.model == "deepseek-reasoner"
        assert test_config.deepseek.fast_model == "deepseek-chat"
        assert test_config.deepseek.max_tokens == 4096
        assert test_config.deepseek.timeout == 120

    def test_whisper_config(self, test_config):
        """Whisper конфиг — локальный, medium, int8, ru."""
        assert test_config.whisper.model_size == "medium"
        assert test_config.whisper.compute_type == "int8"
        assert test_config.whisper.language == "ru"
        assert test_config.whisper.device == "auto"

    def test_finance_config(self, test_config):
        """Финансовый конфиг — сумма процентов = 100%."""
        total = test_config.finance.expense_percent + test_config.finance.savings_percent
        assert abs(total - 100.0) < 0.01

    def test_finance_validate_wrong_percent(self):
        """Валидация ловит неверные проценты."""
        from pds_ultimate.config import FinanceConfig

        fc = FinanceConfig()
        object.__setattr__(fc, "expense_percent", 60.0)
        object.__setattr__(fc, "savings_percent", 60.0)
        with pytest.raises(ValueError, match="100%"):
            fc.validate()

    def test_currency_fixed_rates(self, test_config):
        """Фиксированные курсы: USD/TMT=19.5, USD/CNY=7.1."""
        rates = test_config.currency.fixed_rates
        assert rates["TMT"] == 19.5
        assert rates["CNY"] == 7.1

    def test_logistics_config(self, test_config):
        """Логистика: T+4, вторник, 2 часа, 20:00."""
        assert test_config.logistics.first_status_check_days == 4
        assert test_config.logistics.recurring_check_weekday == 1  # Вторник
        assert test_config.logistics.reminder_hours == 2
        assert test_config.logistics.evening_reminder_hour == 20

    def test_telethon_config(self, test_config):
        """Telethon: 7 чатов, 100 сообщений."""
        assert test_config.telethon.style_analysis_chat_count == 7
        assert test_config.telethon.messages_per_chat == 100

    def test_whatsapp_config(self, test_config):
        """WhatsApp: 3 чата, 100 сообщений."""
        assert test_config.whatsapp.style_analysis_chat_count == 3
        assert test_config.whatsapp.messages_per_chat == 100

    def test_scheduler_config(self, test_config):
        """Планировщик: утро 8:30, отчёт 3 дня, бэкап 3:00."""
        assert test_config.scheduler.morning_brief_hour == 8
        assert test_config.scheduler.morning_brief_minute == 30
        assert test_config.scheduler.report_interval_days == 3
        assert test_config.scheduler.backup_hour == 3

    def test_style_config(self, test_config):
        """Стиль: пересканирование 7 дней, мин. 50 сообщений."""
        assert test_config.style.rescan_interval_days == 7
        assert test_config.style.min_messages_for_profile == 50

    def test_validate_success(self, test_config):
        """Полная валидация проходит."""
        warnings = test_config.validate()
        assert isinstance(warnings, list)


class TestConfigPaths:
    """Тесты путей конфигурации."""

    def test_data_dir_exists(self):
        """Директория данных создаётся."""
        from pds_ultimate.config import DATA_DIR
        assert DATA_DIR.exists()

    def test_database_path(self):
        """Путь к БД — в data/."""
        from pds_ultimate.config import DATABASE_PATH
        assert "pds_ultimate.db" in str(DATABASE_PATH)

    def test_logs_dir_exists(self):
        """Директория логов создаётся."""
        from pds_ultimate.config import LOGS_DIR
        assert LOGS_DIR.exists()
