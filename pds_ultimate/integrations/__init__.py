"""
PDS-Ultimate Integrations
============================
Внешние интеграции: WhatsApp, Gmail, Telethon, Exchange Rates, Google Calendar.
"""

from pds_ultimate.integrations.exchange_rates import (
    ExchangeRateService,
    exchange_service,
)
from pds_ultimate.integrations.gmail import GmailClient, gmail_client
from pds_ultimate.integrations.google_calendar import (
    GoogleCalendarService,
    google_calendar,
)
from pds_ultimate.integrations.telethon_client import TelethonClient, telethon_client
from pds_ultimate.integrations.whatsapp import WhatsAppClient, wa_client

__all__ = [
    "WhatsAppClient",
    "wa_client",
    "GmailClient",
    "gmail_client",
    "TelethonClient",
    "telethon_client",
    "ExchangeRateService",
    "exchange_service",
    "GoogleCalendarService",
    "google_calendar",
]
