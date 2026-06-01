"""
PDS-Ultimate Samsung Calendar Integration
=============================================
Интеграция с Samsung Calendar через CalDAV/ICS/webhook bridge.

Samsung Cloud Calendar НЕ имеет публичного API.
Стратегия подключения:
1. Samsung Calendar → синхронизация с Google → Google Calendar API (рекомендуется)
2. CalDAV-совместимый сервер (Radicale/Nextcloud) как мост
3. ICS-файл экспорт/импорт (ручной)

Данный модуль:
- Синхронизирует Samsung Calendar ↔ локальная БД через Google Calendar API
- Поддерживает ICS-файлы (import/export)
- Управляет общими календарями (shared calendar)
- Уведомления о событиях

Привязка: alexkurumbayev@gmail.com
Общий календарь: "Общий календарь 1"
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from pds_ultimate.config import DATA_DIR, logger

# ═══════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════


class SharedCalendarEvent:
    """Событие из общего Samsung/Google календаря."""

    __slots__ = (
        "id", "title", "description", "location",
        "start", "end", "all_day", "calendar_name",
        "organizer", "attendees", "status", "source",
        "synced_at", "remote_id",
    )

    def __init__(
        self,
        id: str = "",
        title: str = "",
        description: str = "",
        location: str = "",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        all_day: bool = False,
        calendar_name: str = "",
        organizer: str = "",
        attendees: Optional[list[str]] = None,
        status: str = "confirmed",
        source: str = "samsung",
        synced_at: Optional[datetime] = None,
        remote_id: str = "",
    ):
        self.id = id
        self.title = title
        self.description = description
        self.location = location
        self.start = start
        self.end = end
        self.all_day = all_day
        self.calendar_name = calendar_name
        self.organizer = organizer
        self.attendees = attendees or []
        self.status = status
        self.source = source
        self.synced_at = synced_at or datetime.now()
        self.remote_id = remote_id

    @property
    def duration_minutes(self) -> int:
        if self.start and self.end:
            return int((self.end - self.start).total_seconds() / 60)
        return 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "location": self.location,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "all_day": self.all_day,
            "calendar_name": self.calendar_name,
            "organizer": self.organizer,
            "attendees": self.attendees,
            "duration_minutes": self.duration_minutes,
            "status": self.status,
            "source": self.source,
        }

    def __repr__(self) -> str:
        return f"SharedCalendarEvent('{self.title}', {self.start})"


# ═══════════════════════════════════════════════════════════════════════════════
# SAMSUNG CALENDAR SERVICE
# ═══════════════════════════════════════════════════════════════════════════════


class SamsungCalendarService:
    """
    Сервис интеграции с Samsung Calendar.

    Архитектура:
    ┌────────────────┐     ┌──────────────┐     ┌──────────────────┐
    │ Samsung Calendar│ ──→ │ Google Sync  │ ──→ │ Google Calendar  │
    │ (телефон)      │     │ (авто)       │     │ API              │
    └────────────────┘     └──────────────┘     └────────┬─────────┘
                                                         │
                                                         ▼
                                                ┌────────────────┐
                                                │ PDS-Ultimate   │
                                                │ Calendar Agent │
                                                └────────────────┘

    Samsung Calendar автоматически синхронизируется с Google Calendar
    если аккаунт Google добавлен на телефоне Samsung.

    Использование:
        samsung_cal = SamsungCalendarService()
        await samsung_cal.start()
        events = await samsung_cal.get_shared_events()
    """

    # Конфигурация общего календаря
    SHARED_CALENDAR_NAME = "Общий календарь 1"
    LINKED_EMAIL = "alexkurumbayev@gmail.com"
    INVITATION_LINK = (
        "https://groupshare.samsungcloud.com/invitation/calendar/KHA8A0eqx6"
    )

    def __init__(self) -> None:
        self._started = False
        self._google_service = None
        self._shared_calendar_id: Optional[str] = None
        self._events_cache: list[SharedCalendarEvent] = []
        self._last_sync: Optional[datetime] = None
        self._sync_file = Path(DATA_DIR) / "samsung_calendar_sync.json"
        self._total_synced = 0

    @property
    def is_available(self) -> bool:
        return self._started

    @property
    def sync_status(self) -> dict[str, Any]:
        return {
            "connected": self._started,
            "shared_calendar": self.SHARED_CALENDAR_NAME,
            "linked_email": self.LINKED_EMAIL,
            "calendar_id": self._shared_calendar_id,
            "cached_events": len(self._events_cache),
            "last_sync": (
                self._last_sync.isoformat() if self._last_sync else None
            ),
            "total_synced": self._total_synced,
        }

    # ═══════════════════════════════════════════════════════════════════════
    # Lifecycle
    # ═══════════════════════════════════════════════════════════════════════

    async def start(self) -> bool:
        """
        Инициализация: подключение к Google Calendar API
        для доступа к общему Samsung Calendar.

        Samsung Calendar синхронизируется с Google Calendar,
        поэтому мы используем Google Calendar API как мост.
        """
        try:
            from pds_ultimate.integrations.google_calendar import (
                google_calendar,
            )

            # Запускаем Google Calendar если ещё не запущен
            if not google_calendar.is_available:
                success = await google_calendar.start()
                if not success:
                    logger.warning(
                        "[SamsungCalendar] Google Calendar недоступен. "
                        "Samsung Calendar синхронизируется через Google. "
                        "Настройте Google Calendar API."
                    )
                    # Загружаем из локального кэша
                    self._load_cache()
                    self._started = True
                    return True

            self._google_service = google_calendar

            # Ищем общий календарь
            await self._find_shared_calendar()

            # Загружаем кэш
            self._load_cache()

            self._started = True
            logger.info(
                f"[SamsungCalendar] Подключён к '{self.SHARED_CALENDAR_NAME}' "
                f"через Google Calendar (email: {self.LINKED_EMAIL})"
            )
            return True

        except Exception as e:
            logger.warning(f"[SamsungCalendar] Ошибка инициализации: {e}")
            self._load_cache()
            self._started = True
            return True  # Работаем в offline-режиме с кэшем

    async def stop(self) -> None:
        """Остановка сервиса."""
        self._save_cache()
        self._started = False
        self._google_service = None

    async def _find_shared_calendar(self) -> None:
        """Найти ID общего календаря в Google Calendar."""
        if not self._google_service or not self._google_service._service:
            return

        try:
            calendar_list = (
                self._google_service._service.calendarList()
                .list()
                .execute()
            )

            for cal in calendar_list.get("items", []):
                summary = cal.get("summary", "")
                # Ищем по имени или по email владельца
                if (
                    summary == self.SHARED_CALENDAR_NAME
                    or self.LINKED_EMAIL in str(cal)
                ):
                    self._shared_calendar_id = cal.get("id")
                    logger.info(
                        f"[SamsungCalendar] Найден общий календарь: "
                        f"'{summary}' (id: {self._shared_calendar_id})"
                    )
                    return

            logger.info(
                f"[SamsungCalendar] Общий календарь "
                f"'{self.SHARED_CALENDAR_NAME}' не найден в Google. "
                f"Убедитесь, что Samsung Calendar синхронизирован с Google "
                f"и приглашение принято на {self.LINKED_EMAIL}."
            )

        except Exception as e:
            logger.warning(f"[SamsungCalendar] Ошибка поиска календаря: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # CRUD Events
    # ═══════════════════════════════════════════════════════════════════════

    async def get_shared_events(
        self,
        days: int = 7,
    ) -> list[SharedCalendarEvent]:
        """Получить события из общего календаря."""
        # Пробуем Google Calendar API
        if (
            self._google_service
            and self._google_service.is_available
            and self._shared_calendar_id
        ):
            try:
                now = datetime.now()
                events = await self._fetch_google_events(
                    time_min=now,
                    time_max=now + timedelta(days=days),
                )
                self._events_cache = events
                self._last_sync = datetime.now()
                self._total_synced += len(events)
                self._save_cache()
                return events
            except Exception as e:
                logger.warning(
                    f"[SamsungCalendar] Ошибка Google API: {e}. "
                    f"Используем кэш."
                )

        # Fallback: кэш
        return self._events_cache

    async def get_today_events(self) -> list[SharedCalendarEvent]:
        """События на сегодня из общего календаря."""
        events = await self.get_shared_events(days=1)
        today = datetime.now().date()
        return [
            e for e in events
            if e.start and e.start.date() == today
        ]

    async def create_shared_event(
        self,
        title: str,
        start: datetime,
        end: Optional[datetime] = None,
        description: str = "",
        location: str = "",
    ) -> SharedCalendarEvent:
        """Создать событие в общем календаре."""
        if end is None:
            end = start + timedelta(hours=1)

        event = SharedCalendarEvent(
            id=f"samsung_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            title=title,
            description=description,
            location=location,
            start=start,
            end=end,
            calendar_name=self.SHARED_CALENDAR_NAME,
            organizer=self.LINKED_EMAIL,
            source="samsung",
        )

        # Пробуем создать через Google Calendar API
        if (
            self._google_service
            and self._google_service.is_available
            and self._shared_calendar_id
        ):
            try:
                # Временно меняем calendar_id
                original_id = self._google_service._calendar_id
                self._google_service._calendar_id = self._shared_calendar_id

                gcal_event = await self._google_service.create_event(
                    summary=title,
                    start=start,
                    end=end,
                    description=description,
                    location=location,
                )

                self._google_service._calendar_id = original_id

                event.remote_id = gcal_event.id
                logger.info(
                    f"[SamsungCalendar] Событие создано в Google: "
                    f"'{title}' → синхронизируется с Samsung"
                )
            except Exception as e:
                logger.warning(
                    f"[SamsungCalendar] Google create failed: {e}. "
                    f"Сохраняем локально."
                )

        # Сохраняем в кэш
        self._events_cache.append(event)
        self._save_cache()

        return event

    async def import_ics(self, ics_path: str) -> list[SharedCalendarEvent]:
        """
        Импортировать события из ICS-файла.
        Samsung Calendar может экспортировать в .ics формат.
        """
        events: list[SharedCalendarEvent] = []

        try:
            with open(ics_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Парсим ICS вручную (без icalendar)
            current_event: dict[str, str] = {}
            in_event = False

            for line in content.split("\n"):
                line = line.strip()

                if line == "BEGIN:VEVENT":
                    in_event = True
                    current_event = {}
                elif line == "END:VEVENT" and in_event:
                    in_event = False
                    event = self._parse_ics_event(current_event)
                    if event:
                        events.append(event)
                elif in_event and ":" in line:
                    key, _, value = line.partition(":")
                    # Удаляем параметры (DTSTART;TZID=...)
                    key = key.split(";")[0]
                    current_event[key] = value

            self._events_cache.extend(events)
            self._save_cache()

            logger.info(
                f"[SamsungCalendar] Импортировано {len(events)} событий "
                f"из ICS: {ics_path}"
            )

        except Exception as e:
            logger.error(f"[SamsungCalendar] Ошибка импорта ICS: {e}")

        return events

    def export_ics(self, output_path: str = "") -> str:
        """Экспортировать кэшированные события в ICS."""
        if not output_path:
            output_path = str(
                Path(DATA_DIR) / "samsung_calendar_export.ics"
            )

        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            f"PRODID:-//PDS-Ultimate//Samsung Calendar//{datetime.now().year}",
            f"X-WR-CALNAME:{self.SHARED_CALENDAR_NAME}",
        ]

        for event in self._events_cache:
            lines.append("BEGIN:VEVENT")
            lines.append(f"UID:{event.id}")
            lines.append(f"SUMMARY:{event.title}")
            if event.description:
                lines.append(f"DESCRIPTION:{event.description}")
            if event.location:
                lines.append(f"LOCATION:{event.location}")
            if event.start:
                lines.append(
                    f"DTSTART:{event.start.strftime('%Y%m%dT%H%M%S')}"
                )
            if event.end:
                lines.append(
                    f"DTEND:{event.end.strftime('%Y%m%dT%H%M%S')}"
                )
            lines.append(f"STATUS:{event.status.upper()}")
            lines.append(f"ORGANIZER:mailto:{event.organizer}")
            lines.append("END:VEVENT")

        lines.append("END:VCALENDAR")

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        logger.info(
            f"[SamsungCalendar] Экспортировано {len(self._events_cache)} "
            f"событий в {output_path}"
        )
        return output_path

    # ═══════════════════════════════════════════════════════════════════════
    # Sync
    # ═══════════════════════════════════════════════════════════════════════

    async def sync(self) -> dict[str, Any]:
        """
        Полная синхронизация Samsung Calendar ↔ Google Calendar.
        """
        result = {
            "synced": False,
            "events_found": 0,
            "new_events": 0,
            "method": "none",
        }

        if (
            self._google_service
            and self._google_service.is_available
            and self._shared_calendar_id
        ):
            try:
                events = await self._fetch_google_events(
                    time_min=datetime.now() - timedelta(days=7),
                    time_max=datetime.now() + timedelta(days=30),
                )

                old_count = len(self._events_cache)
                self._events_cache = events
                self._last_sync = datetime.now()
                self._total_synced += len(events)
                self._save_cache()

                result["synced"] = True
                result["events_found"] = len(events)
                result["new_events"] = max(0, len(events) - old_count)
                result["method"] = "google_api"

                logger.info(
                    f"[SamsungCalendar] Синхронизация: "
                    f"{len(events)} событий"
                )

            except Exception as e:
                result["error"] = str(e)
                logger.warning(f"[SamsungCalendar] Sync error: {e}")
        else:
            result["method"] = "offline_cache"
            result["events_found"] = len(self._events_cache)

        return result

    # ═══════════════════════════════════════════════════════════════════════
    # Internal helpers
    # ═══════════════════════════════════════════════════════════════════════

    async def _fetch_google_events(
        self,
        time_min: datetime,
        time_max: datetime,
    ) -> list[SharedCalendarEvent]:
        """Получить события из Google Calendar."""
        events: list[SharedCalendarEvent] = []

        if not self._google_service or not self._google_service._service:
            return events

        try:
            events_result = (
                self._google_service._service.events()
                .list(
                    calendarId=self._shared_calendar_id or "primary",
                    timeMin=time_min.isoformat() + "+05:00",
                    timeMax=time_max.isoformat() + "+05:00",
                    maxResults=100,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

            for item in events_result.get("items", []):
                event = self._parse_google_event(item)
                if event:
                    events.append(event)

        except Exception as e:
            logger.error(
                f"[SamsungCalendar] Google events fetch error: {e}"
            )

        return events

    def _parse_google_event(self, item: dict) -> Optional[SharedCalendarEvent]:
        """Парсинг события из Google Calendar API."""
        try:
            start_data = item.get("start", {})
            end_data = item.get("end", {})

            start_str = start_data.get("dateTime") or start_data.get("date")
            end_str = end_data.get("dateTime") or end_data.get("date")

            start = self._parse_dt(start_str)
            end = self._parse_dt(end_str)
            all_day = "date" in start_data and "dateTime" not in start_data

            return SharedCalendarEvent(
                id=item.get("id", ""),
                title=item.get("summary", ""),
                description=item.get("description", ""),
                location=item.get("location", ""),
                start=start,
                end=end,
                all_day=all_day,
                calendar_name=self.SHARED_CALENDAR_NAME,
                organizer=item.get("organizer", {}).get("email", ""),
                attendees=[
                    a.get("email", "")
                    for a in item.get("attendees", [])
                ],
                status=item.get("status", "confirmed"),
                source="samsung_via_google",
                remote_id=item.get("id", ""),
            )
        except Exception as e:
            logger.warning(f"[SamsungCalendar] Parse event error: {e}")
            return None

    def _parse_ics_event(
        self, data: dict[str, str]
    ) -> Optional[SharedCalendarEvent]:
        """Парсинг события из ICS данных."""
        try:
            title = data.get("SUMMARY", "")
            if not title:
                return None

            start = self._parse_ics_dt(data.get("DTSTART", ""))
            end = self._parse_ics_dt(data.get("DTEND", ""))

            return SharedCalendarEvent(
                id=data.get("UID", f"ics_{datetime.now().timestamp()}"),
                title=title,
                description=data.get("DESCRIPTION", ""),
                location=data.get("LOCATION", ""),
                start=start,
                end=end,
                calendar_name=self.SHARED_CALENDAR_NAME,
                organizer=data.get("ORGANIZER", "").replace("mailto:", ""),
                status=data.get("STATUS", "confirmed").lower(),
                source="samsung_ics",
            )
        except Exception:
            return None

    @staticmethod
    def _parse_dt(s: Optional[str]) -> Optional[datetime]:
        """Парсинг datetime из Google Calendar."""
        if not s:
            return None
        try:
            if "T" in s:
                clean = s.replace("Z", "+00:00")
                return datetime.fromisoformat(clean).replace(tzinfo=None)
            return datetime.strptime(s, "%Y-%m-%d")
        except Exception:
            return None

    @staticmethod
    def _parse_ics_dt(s: str) -> Optional[datetime]:
        """Парсинг datetime из ICS формата."""
        if not s:
            return None
        try:
            s = s.replace("Z", "")
            if "T" in s:
                return datetime.strptime(s, "%Y%m%dT%H%M%S")
            return datetime.strptime(s, "%Y%m%d")
        except Exception:
            return None

    def _save_cache(self) -> None:
        """Сохранить кэш событий."""
        try:
            os.makedirs(os.path.dirname(self._sync_file), exist_ok=True)
            data = {
                "events": [e.to_dict() for e in self._events_cache],
                "last_sync": (
                    self._last_sync.isoformat() if self._last_sync else None
                ),
                "calendar_id": self._shared_calendar_id,
                "total_synced": self._total_synced,
            }
            with open(self._sync_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[SamsungCalendar] Cache save error: {e}")

    def _load_cache(self) -> None:
        """Загрузить кэш событий."""
        if not self._sync_file.exists():
            return

        try:
            with open(self._sync_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._shared_calendar_id = data.get("calendar_id")
            self._total_synced = data.get("total_synced", 0)

            if data.get("last_sync"):
                self._last_sync = datetime.fromisoformat(data["last_sync"])

            # Восстанавливаем события
            for evt_data in data.get("events", []):
                event = SharedCalendarEvent(
                    id=evt_data.get("id", ""),
                    title=evt_data.get("title", ""),
                    description=evt_data.get("description", ""),
                    location=evt_data.get("location", ""),
                    start=(
                        datetime.fromisoformat(evt_data["start"])
                        if evt_data.get("start")
                        else None
                    ),
                    end=(
                        datetime.fromisoformat(evt_data["end"])
                        if evt_data.get("end")
                        else None
                    ),
                    all_day=evt_data.get("all_day", False),
                    calendar_name=evt_data.get("calendar_name", ""),
                    organizer=evt_data.get("organizer", ""),
                    attendees=evt_data.get("attendees", []),
                    status=evt_data.get("status", "confirmed"),
                    source=evt_data.get("source", "samsung"),
                )
                self._events_cache.append(event)

            logger.info(
                f"[SamsungCalendar] Кэш загружен: "
                f"{len(self._events_cache)} событий"
            )

        except Exception as e:
            logger.warning(f"[SamsungCalendar] Cache load error: {e}")

    def get_setup_instructions(self) -> str:
        """Инструкция по настройке синхронизации."""
        return (
            "📱 Настройка Samsung Calendar → PDS-Ultimate:\n\n"
            "1️⃣ На телефоне Samsung:\n"
            "   • Откройте Настройки → Аккаунты → Google\n"
            "   • Войдите в alexkurumbayev@gmail.com\n"
            "   • Включите синхронизацию Календаря\n\n"
            "2️⃣ Samsung Calendar → Google:\n"
            "   • Откройте Samsung Calendar\n"
            "   • Перейдите к общему календарю\n"
            "   • Он автоматически синхронизируется с Google\n\n"
            "3️⃣ Приглашение:\n"
            f"   • Ссылка: {self.INVITATION_LINK}\n"
            f"   • Email: {self.LINKED_EMAIL}\n\n"
            "4️⃣ На сервере:\n"
            "   • Настройте Google Calendar API (client_secret.json)\n"
            "   • Запустите: samsung_calendar.start()\n"
            "   • Календарь будет доступен через бот"
        )


# ─── Глобальный экземпляр ────────────────────────────────────────────────────

samsung_calendar = SamsungCalendarService()
