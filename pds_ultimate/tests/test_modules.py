"""
Тесты модулей — инициализация и импорт.
"""


class TestModuleImports:
    """Все модули импортируются без ошибок."""

    def test_import_order_manager(self):
        from pds_ultimate.modules.logistics.order_manager import OrderManager
        assert OrderManager is not None

    def test_import_item_tracker(self):
        from pds_ultimate.modules.logistics.item_tracker import ItemTracker
        assert ItemTracker is not None

    def test_import_delivery_calc(self):
        from pds_ultimate.modules.logistics.delivery_calc import DeliveryCalculator
        assert DeliveryCalculator is not None

    def test_import_archive(self):
        from pds_ultimate.modules.logistics.archive import ArchiveManager
        assert ArchiveManager is not None

    def test_import_master_finance(self):
        from pds_ultimate.modules.finance.master_finance import MasterFinance
        assert MasterFinance is not None

    def test_import_currency(self):
        from pds_ultimate.modules.finance.currency import CurrencyManager
        assert CurrencyManager is not None

    def test_import_profit_calc(self):
        from pds_ultimate.modules.finance.profit_calc import ProfitCalculator
        assert ProfitCalculator is not None

    def test_import_sync_engine(self):
        from pds_ultimate.modules.finance.sync_engine import SyncEngine
        assert SyncEngine is not None

    def test_import_style_analyzer(self):
        from pds_ultimate.modules.secretary.style_analyzer import StyleAnalyzer
        assert StyleAnalyzer is not None

    def test_import_vip_hub(self):
        from pds_ultimate.modules.secretary.vip_hub import VIPHub
        assert VIPHub is not None

    def test_import_auto_responder(self):
        from pds_ultimate.modules.secretary.auto_responder import AutoResponder
        assert AutoResponder is not None

    def test_import_calendar_mgr(self):
        from pds_ultimate.modules.secretary.calendar_mgr import CalendarManager
        assert CalendarManager is not None

    def test_import_morning_brief(self):
        from pds_ultimate.modules.executive.morning_brief import MorningBrief
        assert MorningBrief is not None

    def test_import_backup_security(self):
        from pds_ultimate.modules.executive.backup_security import (
            BackupManager,
            SecurityManager,
        )
        assert BackupManager is not None
        assert SecurityManager is not None

    def test_import_file_manager(self):
        from pds_ultimate.modules.files.file_manager import FileManager
        assert FileManager is not None


class TestModuleInit:
    """Модули инициализируются с session_factory."""

    def test_order_manager_init(self, session_factory):
        from pds_ultimate.modules.logistics.order_manager import OrderManager
        mgr = OrderManager(session_factory)
        assert mgr is not None

    def test_item_tracker_init(self, session_factory):
        from pds_ultimate.modules.logistics.item_tracker import ItemTracker
        tracker = ItemTracker(session_factory)
        assert tracker is not None

    def test_master_finance_init(self, session_factory):
        from pds_ultimate.modules.finance.master_finance import MasterFinance
        mf = MasterFinance(session_factory)
        assert mf is not None

    def test_calendar_mgr_init(self, session_factory):
        from pds_ultimate.modules.secretary.calendar_mgr import CalendarManager
        cal = CalendarManager(session_factory)
        assert cal is not None

    def test_morning_brief_init(self, session_factory):
        from pds_ultimate.modules.executive.morning_brief import MorningBrief
        mb = MorningBrief(session_factory)
        assert mb is not None

    def test_file_manager_init(self, session_factory):
        from pds_ultimate.modules.files.file_manager import FileManager
        fm = FileManager(session_factory)
        assert fm is not None


class TestIntegrationImports:
    """Интеграции импортируются."""

    def test_import_whatsapp(self):
        from pds_ultimate.integrations.whatsapp import WhatsAppClient, wa_client
        assert WhatsAppClient is not None
        assert wa_client is not None

    def test_import_gmail(self):
        from pds_ultimate.integrations.gmail import GmailClient, gmail_client
        assert GmailClient is not None
        assert gmail_client is not None

    def test_import_telethon(self):
        from pds_ultimate.integrations.telethon_client import (
            TelethonClient,
            telethon_client,
        )
        assert TelethonClient is not None
        assert telethon_client is not None

    def test_import_integrations_init(self):
        from pds_ultimate.integrations import (
            wa_client,
        )
        assert wa_client is not None


class TestBotImports:
    """Bot модули импортируются."""

    def test_import_conversation(self):
        from pds_ultimate.bot.conversation import (
            ConversationManager,
            ConversationState,
        )
        assert ConversationManager is not None
        assert ConversationState is not None

    def test_import_middlewares(self):
        from pds_ultimate.bot.middlewares import (
            AuthMiddleware,
        )
        assert AuthMiddleware is not None

    def test_import_handlers(self):
        from pds_ultimate.bot.handlers import files, universal, voice
        assert universal is not None
        assert voice is not None
        assert files is not None


class TestCoreImports:
    """Core модули импортируются."""

    def test_import_llm_engine(self):
        from pds_ultimate.core.llm_engine import LLMEngine, llm_engine
        assert LLMEngine is not None
        assert llm_engine is not None

    def test_import_scheduler(self):
        from pds_ultimate.core.scheduler import TaskScheduler, scheduler
        assert TaskScheduler is not None
        assert scheduler is not None

    def test_import_database(self):
        from pds_ultimate.core.database import Base, init_database
        assert init_database is not None
        assert Base is not None
