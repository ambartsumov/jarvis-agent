"""
PDS-Ultimate Modular Tools — World-Class Architecture
======================================================
Модуляризация бизнес-инструментов на 6 доменов.

АРХИТЕКТУРА:
1. logistics_tools.py — заказы, товары, доставка, трек-номера
2. finance_tools.py — доходы, расходы, прибыль, валюты
3. communication_tools.py — Telegram, WhatsApp, email
4. file_tools.py — Excel, Word, PDF, создание файлов
5. web_tools.py — поиск, браузер, скрапинг
6. system_tools.py — память, напоминания, календарь, системные

КАЖДЫЙ МОДУЛЬ:
- Независимый импорт
- Свои инструменты с описанием
- Unit tests
- Error handling
"""

from pds_ultimate.core.tools_modular.logistics_tools import register_logistics_tools
from pds_ultimate.core.tools_modular.finance_tools import register_finance_tools
from pds_ultimate.core.tools_modular.communication_tools import register_communication_tools
from pds_ultimate.core.tools_modular.file_tools import register_file_tools
from pds_ultimate.core.tools_modular.web_tools import register_web_tools
from pds_ultimate.core.tools_modular.system_tools import register_system_tools


def register_all_modular_tools(registry) -> None:
    """Зарегистрировать все модульные инструменты в реестре."""
    register_logistics_tools(registry)
    register_finance_tools(registry)
    register_communication_tools(registry)
    register_file_tools(registry)
    register_web_tools(registry)
    register_system_tools(registry)


__all__ = [
    # Logistics
    "tool_create_order",
    "tool_get_orders_status",
    "tool_update_order_status",
    "tool_add_tracking",
    "tool_search_orders",
    "tool_archive_order",
    "tool_get_order_history",
    "tool_anti_forget_check",
    
    # Finance
    "tool_set_income",
    "tool_set_expense",
    "tool_set_delivery_cost",
    "tool_get_profit_report",
    "tool_convert_currency",
    "tool_get_financial_summary",
    "tool_export_finance_excel",
    
    # Communication
    "tool_send_telegram_message",
    "tool_send_whatsapp_message",
    "tool_read_telegram_chat",
    "tool_analyze_chat_style",
    
    # Files
    "tool_create_excel",
    "tool_read_excel",
    "tool_create_word",
    "tool_read_pdf",
    "tool_create_report",
    "tool_ocr_image",
    
    # Web
    "tool_web_search",
    "tool_browse_page",
    "tool_screenshot",
    "tool_deep_research",
    "tool_summarize_url",
    "tool_translate",
    
    # System
    "tool_save_memory",
    "tool_search_memory",
    "tool_create_reminder",
    "tool_get_schedule",
    "tool_add_event",
    
    # Registration
    "register_all_modular_tools",
    "register_logistics_tools",
    "register_finance_tools",
    "register_communication_tools",
    "register_file_tools",
    "register_web_tools",
    "register_system_tools",
]

# Import tools for direct access
from pds_ultimate.core.tools_modular.logistics_tools import *
from pds_ultimate.core.tools_modular.finance_tools import *
from pds_ultimate.core.tools_modular.communication_tools import *
from pds_ultimate.core.tools_modular.file_tools import *
from pds_ultimate.core.tools_modular.web_tools import *
from pds_ultimate.core.tools_modular.system_tools import *
