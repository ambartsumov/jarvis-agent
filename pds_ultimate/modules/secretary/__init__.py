"""
Secretary Module
- StyleAnalyzer: Анализ стиля общения (TG/WA)
- VIPHub: Управление VIP-контактами
- AutoResponder: Авто-ответчик (занятость из БД)
- CalendarManager: Календарь в памяти (БД), 30-мин напоминания
"""

from pds_ultimate.modules.secretary.auto_responder import AutoResponder
from pds_ultimate.modules.secretary.calendar_mgr import CalendarManager
from pds_ultimate.modules.secretary.style_analyzer import StyleAnalyzer
from pds_ultimate.modules.secretary.vip_hub import VIPHub

__all__ = [
    "StyleAnalyzer",
    "VIPHub",
    "AutoResponder",
    "CalendarManager",
]
