"""
PDS-Ultimate Google Calendar Integration
============================================
Google Calendar API для управления встречами, конфликт-менеджмента,
авто-ответчика и утреннего брифинга.

По ТЗ §2.2/§2.3:
- Event Manager: создание встреч из текста/голоса
- Конфликт-менеджер: наложения, альтернативы, «нет времени на обед»
- Авто-ответчик: если занят → «Я на встрече до 15:00»
- Гео-учёт: адрес → навигатор за 15 минут до выезда
- Morning Brief: список встреч на день

Credentials: Google OAuth2 (client_secret JSON + token pickle)
"""

from __future__ import annotations

import pickle
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from pds_ultimate.config import (
    CREDENTIALS_DIR,
    logger,
)

# ─── Data Models ─────────────────────────────────────────────────────────────


class CalendarEvent:
    """Событие календаря."""

    __slots__ = (
        "id", "summary", "description", "location",
        "start", "end", "all_day", "attendees",
        "reminders", "status", "source",
    )

    def __init__(
        self,
        id: str = "",
        summary: str = "",
        description: str = "",
        location: str = "",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        all_day: bool = False,
        attendees: Optional[list[str]] = None,
        reminders: Optional[list[int]] = None,
        status: str = "confirmed",
        source: str = "google",
    ):
        self.id = id
        self.summary = summary
        self.description = description
        self.location = location
        self.start = start
        self.end = end
        self.all_day = all_day
        self.attendees = attendees or []
        self.reminders = reminders or [15]  # минут до
        self.status = status
        self.source = source

    @property
    def duration_minutes(self) -> int:
        if self.start and self.end:
            return int((self.end - self.start).total_seconds() / 60)
        return 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "summary": self.summary,
            "description": self.description,
            "location": self.location,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "all_day": self.all_day,
            "attendees": self.attendees,
            "duration_minutes": self.duration_minutes,
            "status": self.status,
        }

    def __repr__(self) -> str:
        return f"CalendarEvent('{self.summary}', {self.start})"


class ConflictInfo:
    """Информация о конфликте расписания."""

    def __init__(
        self,
        event_a: CalendarEvent,
        event_b: CalendarEvent,
        overlap_minutes: int = 0,
        suggestion: str = "",
    ):
        self.event_a = event_a
        self.event_b = event_b
        self.overlap_minutes = overlap_minutes
        self.suggestion = suggestion

    def to_dict(self) -> dict:
        return {
            "event_a": self.event_a.summary,
            "event_b": self.event_b.summary,
            "overlap_minutes": self.overlap_minutes,
            "suggestion": self.suggestion,
        }


class FreeSlot:
    """Свободное окно в расписании."""

    def __init__(self, start: datetime, end: datetime):
        self.start = start
        self.end = end

    @property
    def duration_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() / 60)

    def to_dict(self) -> dict:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "duration_minutes": self.duration_minutes,
        }


# ─── Calendar Service ────────────────────────────────────────────────────────

class GoogleCalendarService:
    """
    Сервис работы с Google Calendar API.

    Архитектура:
    - OAuth2 авторизация (client_secret + token)
    - CRUD операции с событиями
    - Конфликт-менеджер
    - Поиск свободных слотов
    - Форматирование для бота и утреннего брифинга

    Использование:
        await gcal.start()
        events = await gcal.get_today_events()
        conflict = gcal.check_conflict(new_event, existing_events)
    """

    TOKEN_FILE = "calendar_token.pickle"
    SCOPES = ["https://www.googleapis.com/auth/calendar"]

    def __init__(self):
        self._service = None
        self._calendar_id = "primary"
        self._timezone = "Asia/Ashgabat"
        self._started = False
        self._credentials_path: Optional[Path] = None

        # Ищем client_secret в credentials/
        for f in CREDENTIALS_DIR.glob("client_secret_*.json"):
            self._credentials_path = f
            break

    @property
    def is_available(self) -> bool:
        return self._started and self._service is not None

    # ═══════════════════════════════════════════════════════════════════════
    # Lifecycle
    # ═══════════════════════════════════════════════════════════════════════

    async def start(self) -> bool:
        """Инициализация Google Calendar API."""
        if not self._credentials_path:
            logger.warning(
                "[GoogleCalendar] client_secret_*.json не найден в credentials/"
            )
            return False

        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build

            creds = None
            token_path = CREDENTIALS_DIR / self.TOKEN_FILE

            # Загружаем существующий токен
            if token_path.exists():
                with open(token_path, "rb") as f:
                    creds = pickle.load(f)

            # Обновляем/получаем новый токен
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    # НЕ запускаем run_local_server — он блокирует навсегда.
                    raise RuntimeError(
                        f"Google Calendar токен не найден: {token_path}. "
                        f"Запустите OAuth вручную: "
                        f"python -m pds_ultimate.integrations.gmail_auth"
                    )

                # Сохраняем
                with open(token_path, "wb") as f:
                    pickle.dump(creds, f)

            self._service = build("calendar", "v3", credentials=creds)
            self._started = True
            logger.info("[GoogleCalendar] Подключение установлено")
            return True

        except ImportError:
            logger.warning(
                "[GoogleCalendar] google-api-python-client не установлен"
            )
            return False
        except Exception as e:
            logger.warning(f"[GoogleCalendar] Ошибка подключения: {e}")
            return False

    async def stop(self):
        """Закрытие сервиса."""
        self._service = None
        self._started = False

    # ═══════════════════════════════════════════════════════════════════════
    # CRUD Events
    # ═══════════════════════════════════════════════════════════════════════

    async def create_event(
        self,
        summary: str,
        start: datetime,
        end: Optional[datetime] = None,
        description: str = "",
        location: str = "",
        attendees: Optional[list[str]] = None,
        reminders_minutes: Optional[list[int]] = None,
    ) -> CalendarEvent:
        """Создать событие в Google Calendar."""
        if end is None:
            end = start + timedelta(hours=1)

        if reminders_minutes is None:
            reminders_minutes = [15]

        body = {
            "summary": summary,
            "description": description,
            "location": location,
            "start": {
                "dateTime": start.isoformat(),
                "timeZone": self._timezone,
            },
            "end": {
                "dateTime": end.isoformat(),
                "timeZone": self._timezone,
            },
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": m}
                    for m in reminders_minutes
                ],
            },
        }

        if attendees:
            body["attendees"] = [{"email": a} for a in attendees]

        if self._service:
            try:
                result = self._service.events().insert(
                    calendarId=self._calendar_id, body=body
                ).execute()

                return CalendarEvent(
                    id=result.get("id", ""),
                    summary=summary,
                    description=description,
                    location=location,
                    start=start,
                    end=end,
                    attendees=attendees or [],
                    reminders=reminders_minutes,
                )
            except Exception as e:
                logger.error(f"[GoogleCalendar] create_event failed: {e}")

        # Fallback: возвращаем локальный объект
        return CalendarEvent(
            id="local_" + datetime.now().strftime("%Y%m%d%H%M%S"),
            summary=summary,
            description=description,
            location=location,
            start=start,
            end=end,
            attendees=attendees or [],
            reminders=reminders_minutes,
            source="local",
        )

    async def get_events(
        self,
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
        max_results: int = 50,
    ) -> list[CalendarEvent]:
        """Получить события за период."""
        if time_min is None:
            time_min = datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        if time_max is None:
            time_max = time_min + timedelta(days=1)

        if not self._service:
            return []

        try:
            tz = timezone(timedelta(hours=5))  # Asia/Ashgabat = UTC+5
            events_result = self._service.events().list(
                calendarId=self._calendar_id,
                timeMin=time_min.astimezone(tz).isoformat()
                if time_min.tzinfo else time_min.isoformat() + "+05:00",
                timeMax=time_max.astimezone(tz).isoformat()
                if time_max.tzinfo else time_max.isoformat() + "+05:00",
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            ).execute()

            items = events_result.get("items", [])
            return [self._parse_event(item) for item in items]

        except Exception as e:
            logger.error(f"[GoogleCalendar] get_events failed: {e}")
            return []

    async def get_today_events(self) -> list[CalendarEvent]:
        """Получить события на сегодня."""
        now = datetime.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return await self.get_events(start, end)

    async def get_upcoming_events(
        self,
        hours: int = 2,
    ) -> list[CalendarEvent]:
        """Получить ближайшие события (через N часов)."""
        now = datetime.now()
        return await self.get_events(now, now + timedelta(hours=hours))

    async def delete_event(self, event_id: str) -> bool:
        """Удалить событие."""
        if not self._service:
            return False

        try:
            self._service.events().delete(
                calendarId=self._calendar_id,
                eventId=event_id,
            ).execute()
            return True
        except Exception as e:
            logger.error(f"[GoogleCalendar] delete_event failed: {e}")
            return False

    async def update_event(
        self,
        event_id: str,
        **kwargs,
    ) -> Optional[CalendarEvent]:
        """Обновить событие."""
        if not self._service:
            return None

        try:
            # Получить текущее
            event = self._service.events().get(
                calendarId=self._calendar_id,
                eventId=event_id,
            ).execute()

            # Обновить поля
            for key, value in kwargs.items():
                if key == "summary":
                    event["summary"] = value
                elif key == "description":
                    event["description"] = value
                elif key == "location":
                    event["location"] = value
                elif key == "start" and isinstance(value, datetime):
                    event["start"]["dateTime"] = value.isoformat()
                elif key == "end" and isinstance(value, datetime):
                    event["end"]["dateTime"] = value.isoformat()

            result = self._service.events().update(
                calendarId=self._calendar_id,
                eventId=event_id,
                body=event,
            ).execute()

            return self._parse_event(result)

        except Exception as e:
            logger.error(f"[GoogleCalendar] update_event failed: {e}")
            return None

    # ═══════════════════════════════════════════════════════════════════════
    # Конфликт-менеджер
    # ═══════════════════════════════════════════════════════════════════════

    def check_conflicts(
        self,
        new_event: CalendarEvent,
        existing_events: list[CalendarEvent],
    ) -> list[ConflictInfo]:
        """
        Проверить наложения нового события с существующими.
        Возвращает список конфликтов.
        """
        conflicts = []

        if not new_event.start or not new_event.end:
            return conflicts

        for existing in existing_events:
            if not existing.start or not existing.end:
                continue
            if existing.status == "cancelled":
                continue

            # Проверка наложения
            overlap = self._calculate_overlap(
                new_event.start, new_event.end,
                existing.start, existing.end,
            )

            if overlap > 0:
                suggestion = self._generate_suggestion(
                    new_event, existing, existing_events
                )
                conflicts.append(ConflictInfo(
                    event_a=new_event,
                    event_b=existing,
                    overlap_minutes=overlap,
                    suggestion=suggestion,
                ))

        return conflicts

    def check_lunch_break(
        self,
        events: list[CalendarEvent],
        lunch_start_hour: int = 12,
        lunch_end_hour: int = 14,
    ) -> Optional[str]:
        """
        Проверить, есть ли время на обед.
        Возвращает предупреждение если нет.
        """
        for event in events:
            if not event.start or not event.end:
                continue

            # Событие перекрывает обеденное время
            if (event.start.hour < lunch_end_hour and
                    event.end.hour > lunch_start_hour):
                # Проверяем, полностью ли закрыт обед
                lunch_start = event.start.replace(
                    hour=lunch_start_hour, minute=0
                )
                lunch_end = event.start.replace(
                    hour=lunch_end_hour, minute=0
                )

                overlap = self._calculate_overlap(
                    event.start, event.end, lunch_start, lunch_end
                )
                if overlap >= 60:
                    return (
                        f"⚠️ Нет времени на обед! Событие "
                        f"«{event.summary}» занимает {overlap} мин "
                        f"в обеденное время ({lunch_start_hour}:00-"
                        f"{lunch_end_hour}:00)"
                    )

        return None

    def find_free_slots(
        self,
        events: list[CalendarEvent],
        day_start_hour: int = 9,
        day_end_hour: int = 18,
        min_duration_minutes: int = 30,
        reference_date: Optional[datetime] = None,
    ) -> list[FreeSlot]:
        """Найти свободные окна в расписании."""
        if reference_date is None:
            reference_date = datetime.now()

        day_start = reference_date.replace(
            hour=day_start_hour, minute=0, second=0, microsecond=0
        )
        day_end = reference_date.replace(
            hour=day_end_hour, minute=0, second=0, microsecond=0
        )

        # Сортируем по началу
        sorted_events = sorted(
            [e for e in events if e.start and e.end],
            key=lambda e: e.start,
        )

        free_slots = []
        current = day_start

        for event in sorted_events:
            if event.end <= day_start or event.start >= day_end:
                continue

            event_start = max(event.start, day_start)

            if event_start > current:
                gap_minutes = int(
                    (event_start - current).total_seconds() / 60
                )
                if gap_minutes >= min_duration_minutes:
                    free_slots.append(FreeSlot(current, event_start))

            current = max(current, min(event.end, day_end))

        # Окно после последнего события
        if current < day_end:
            gap_minutes = int((day_end - current).total_seconds() / 60)
            if gap_minutes >= min_duration_minutes:
                free_slots.append(FreeSlot(current, day_end))

        return free_slots

    # ═══════════════════════════════════════════════════════════════════════
    # Авто-ответчик: проверка занятости
    # ═══════════════════════════════════════════════════════════════════════

    async def is_busy_now(self) -> Optional[CalendarEvent]:
        """
        Проверить, занят ли пользователь сейчас.
        Возвращает текущее событие или None.
        """
        now = datetime.now()
        events = await self.get_events(
            now - timedelta(minutes=5),
            now + timedelta(minutes=5),
        )

        for event in events:
            if event.start and event.end:
                if event.start <= now <= event.end:
                    return event

        return None

    def get_busy_message(self, event: CalendarEvent) -> str:
        """Сгенерировать сообщение «я на встрече»."""
        if event.end:
            end_str = event.end.strftime("%H:%M")
            return f"Я сейчас на встрече, освобожусь к {end_str}. Отвечу позже."
        return "Я сейчас занят, отвечу позже."

    # ═══════════════════════════════════════════════════════════════════════
    # Форматирование
    # ═══════════════════════════════════════════════════════════════════════

    def format_events_list(self, events: list[CalendarEvent]) -> str:
        """Форматировать список событий для бота."""
        if not events:
            return "📅 На сегодня встреч нет."

        lines = [f"📅 Встречи ({len(events)}):\n"]

        for i, event in enumerate(events, 1):
            time_str = ""
            if event.start:
                time_str = event.start.strftime("%H:%M")
                if event.end:
                    time_str += f"–{event.end.strftime('%H:%M')}"

            location = f" 📍 {event.location}" if event.location else ""
            lines.append(f"  {i}. {time_str} — {event.summary}{location}")

        return "\n".join(lines)

    def format_day_summary(self, events: list[CalendarEvent]) -> str:
        """Саммари дня для утреннего брифинга."""
        if not events:
            return "📅 Встречи: нет"

        first = events[0]
        first_time = first.start.strftime("%H:%M") if first.start else "?"

        summary = f"📅 Встречи: {len(events)} (первая в {first_time})"

        # Предупреждение об обеде
        lunch_warning = self.check_lunch_break(events)
        if lunch_warning:
            summary += f"\n{lunch_warning}"

        return summary

    def format_free_slots(self, slots: list[FreeSlot]) -> str:
        """Форматировать свободные окна."""
        if not slots:
            return "⏰ Свободных окон нет."

        lines = ["⏰ Свободные окна:\n"]
        for slot in slots:
            start = slot.start.strftime("%H:%M")
            end = slot.end.strftime("%H:%M")
            lines.append(
                f"  🟢 {start}–{end} ({slot.duration_minutes} мин)"
            )

        return "\n".join(lines)

    # ═══════════════════════════════════════════════════════════════════════
    # Internal
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _calculate_overlap(
        start_a: datetime,
        end_a: datetime,
        start_b: datetime,
        end_b: datetime,
    ) -> int:
        """Вычислить наложение в минутах."""
        overlap_start = max(start_a, start_b)
        overlap_end = min(end_a, end_b)

        if overlap_start < overlap_end:
            return int((overlap_end - overlap_start).total_seconds() / 60)
        return 0

    def _generate_suggestion(
        self,
        new_event: CalendarEvent,
        conflicting: CalendarEvent,
        all_events: list[CalendarEvent],
    ) -> str:
        """Предложить альтернативу при конфликте."""
        if not new_event.start or not new_event.end:
            return "Укажите время для нового события"

        duration = new_event.duration_minutes

        # Попробовать сразу после конфликтующего
        if conflicting.end:
            after_start = conflicting.end + timedelta(minutes=15)
            after_end = after_start + timedelta(minutes=duration)

            # Проверить, свободно ли это время
            has_conflict = False
            for evt in all_events:
                if evt.start and evt.end:
                    if self._calculate_overlap(
                        after_start, after_end, evt.start, evt.end
                    ) > 0:
                        has_conflict = True
                        break

            if not has_conflict:
                return (
                    f"Предлагаю перенести на "
                    f"{after_start.strftime('%H:%M')}–"
                    f"{after_end.strftime('%H:%M')}"
                )

        return "Попробуйте другой день или сократите длительность"

    def _parse_event(self, item: dict) -> CalendarEvent:
        """Парсинг события из Google Calendar API response."""
        start_data = item.get("start", {})
        end_data = item.get("end", {})

        start = self._parse_datetime(
            start_data.get("dateTime") or start_data.get("date")
        )
        end = self._parse_datetime(
            end_data.get("dateTime") or end_data.get("date")
        )
        all_day = "date" in start_data and "dateTime" not in start_data

        attendees = [
            a.get("email", "")
            for a in item.get("attendees", [])
        ]

        return CalendarEvent(
            id=item.get("id", ""),
            summary=item.get("summary", ""),
            description=item.get("description", ""),
            location=item.get("location", ""),
            start=start,
            end=end,
            all_day=all_day,
            attendees=attendees,
            status=item.get("status", "confirmed"),
            source="google",
        )

    @staticmethod
    def _parse_datetime(s: Optional[str]) -> Optional[datetime]:
        """Парсинг datetime строки из Google Calendar."""
        if not s:
            return None

        try:
            # ISO format with timezone
            if "T" in s:
                # Remove timezone suffix for naive parsing
                clean = s.replace("Z", "+00:00")
                return datetime.fromisoformat(clean).replace(tzinfo=None)
            else:
                # Date only (all-day event)
                return datetime.strptime(s, "%Y-%m-%d")
        except Exception:
            return None


# ─── Глобальный экземпляр ────────────────────────────────────────────────────

google_calendar = GoogleCalendarService()
