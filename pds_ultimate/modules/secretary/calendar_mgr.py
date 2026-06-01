"""
PDS-Ultimate Calendar Manager
================================
Менеджер календаря (хранение в БД / памяти системы).

По ТЗ:
- Встречи, звонки, рейсы
- Предупреждения о конфликтах
- Учёт часовых поясов
- Утром даёт план на день, спрашивает что добавить/убрать
- За 30 минут до события — предупреждение
- БЕЗ Google Calendar — всё в памяти
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Optional

from pds_ultimate.config import logger
from pds_ultimate.core.llm_engine import llm_engine


class CalendarManager:
    """
    Менеджер событий: CRUD + конфликт-детекция + DeepSeek-парсинг.
    """

    def __init__(self, db_session_factory):
        self._session_factory = db_session_factory

    # ═══════════════════════════════════════════════════════════════════════
    # Создание / парсинг из текста
    # ═══════════════════════════════════════════════════════════════════════

    async def create_from_text(self, text: str) -> dict:
        """
        Парсить свободный текст → создать событие.
        «Встреча с Ли Вей в пятницу в 14:00 в офисе»
        Возвращает {"event_id": ..., "title": ..., "conflicts": [...]}
        """
        now = datetime.now()
        prompt = (
            f"Сегодня {now.strftime('%Y-%m-%d %A %H:%M')}.\n"
            f"Распарси текст в событие календаря:\n«{text}»\n\n"
            f"Верни JSON:\n"
            f'{{"title":"назв","start":"YYYY-MM-DD HH:MM",'
            f'"end":"YYYY-MM-DD HH:MM","location":"если есть",'
            f'"description":"если есть"}}\n'
            f"Если время конца не указано — ставь +1 час от начала."
        )

        response = await llm_engine.chat(
            message=prompt,
            task_type="parse",
            temperature=0.1,
            json_mode=True,
        )

        try:
            data = json.loads(response)
        except Exception:
            return {"error": f"Не удалось распарсить: {response}"}

        start_time = datetime.strptime(data["start"], "%Y-%m-%d %H:%M")
        end_str = data.get("end")
        if end_str:
            end_time = datetime.strptime(end_str, "%Y-%m-%d %H:%M")
        else:
            end_time = start_time + timedelta(hours=1)

        # Конфликт-детекция
        conflicts = await self._find_conflicts(start_time, end_time)

        # Создание в БД
        event_id = await self._save_event(
            title=data.get("title", text[:100]),
            start_time=start_time,
            end_time=end_time,
            location=data.get("location"),
            description=data.get("description"),
        )

        result = {
            "event_id": event_id,
            "title": data.get("title", text[:100]),
            "start": start_time.strftime("%Y-%m-%d %H:%M"),
            "end": end_time.strftime("%Y-%m-%d %H:%M"),
            "location": data.get("location", ""),
        }

        if conflicts:
            result["conflicts"] = conflicts

        return result

    # ═══════════════════════════════════════════════════════════════════════
    # CRUD
    # ═══════════════════════════════════════════════════════════════════════

    async def get_today(self) -> list[dict]:
        """Все события на сегодня."""
        now = datetime.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return await self._get_events_range(start, end)

    async def get_upcoming(self, days: int = 7) -> list[dict]:
        """События на ближайшие N дней."""
        now = datetime.now()
        end = now + timedelta(days=days)
        return await self._get_events_range(now, end)

    async def cancel_event(self, event_id: int) -> bool:
        """Отменить событие."""
        with self._session_factory() as session:
            from pds_ultimate.core.database import CalendarEvent, TaskStatus

            event = session.query(CalendarEvent).filter(
                CalendarEvent.id == event_id,
            ).first()

            if not event:
                return False

            event.status = TaskStatus.CANCELLED
            session.commit()
            logger.info(f"Event {event_id} cancelled")
            return True

    async def reschedule(self, event_id: int, new_text: str) -> dict:
        """Перенести событие на основе текста."""
        # Отменяем старое
        await self.cancel_event(event_id)
        # Создаём новое
        return await self.create_from_text(new_text)

    # ═══════════════════════════════════════════════════════════════════════
    # Конфликт-детекция
    # ═══════════════════════════════════════════════════════════════════════

    async def _find_conflicts(
        self,
        start: datetime,
        end: datetime,
        exclude_id: Optional[int] = None,
    ) -> list[dict]:
        """Найти пересекающиеся события."""
        with self._session_factory() as session:
            from pds_ultimate.core.database import CalendarEvent, TaskStatus

            query = session.query(CalendarEvent).filter(
                CalendarEvent.start_time < end,
                CalendarEvent.end_time > start,
                CalendarEvent.status != TaskStatus.CANCELLED,
            )

            if exclude_id:
                query = query.filter(CalendarEvent.id != exclude_id)

            conflicts = []
            for evt in query.all():
                conflicts.append({
                    "id": evt.id,
                    "title": evt.title,
                    "start": evt.start_time.strftime("%Y-%m-%d %H:%M"),
                    "end": evt.end_time.strftime("%Y-%m-%d %H:%M"),
                })

            return conflicts

    # ═══════════════════════════════════════════════════════════════════════
    # Форматирование для бота
    # ═══════════════════════════════════════════════════════════════════════

    def format_event(self, event: dict) -> str:
        """Отформатировать одно событие."""
        parts = [f"📅 {event['title']}"]
        parts.append(f"🕐 {event['start']} — {event['end']}")

        if event.get("location"):
            parts.append(f"📍 {event['location']}")

        if event.get("description"):
            parts.append(f"📝 {event['description']}")

        if event.get("conflicts"):
            parts.append("\n⚠️ Конфликты:")
            for c in event["conflicts"]:
                parts.append(f"  • {c['title']} ({c['start']}–{c['end']})")

        return "\n".join(parts)

    def format_day_schedule(self, events: list[dict]) -> str:
        """Отформатировать расписание на день."""
        if not events:
            return "📅 На сегодня событий нет."

        lines = ["📅 Расписание на сегодня:\n"]
        for i, evt in enumerate(events, 1):
            lines.append(
                f"{i}. {evt['start'][-5:]}–{evt['end'][-5:]} | "
                f"{evt['title']}"
                + (f" 📍{evt.get('location', '')}" if evt.get("location") else "")
            )

        return "\n".join(lines)

    # ═══════════════════════════════════════════════════════════════════════
    # Internal
    # ═══════════════════════════════════════════════════════════════════════

    async def _get_events_range(
        self,
        start: datetime,
        end: datetime,
    ) -> list[dict]:
        """Получить события в диапазоне."""
        with self._session_factory() as session:
            from pds_ultimate.core.database import CalendarEvent, TaskStatus

            events = (
                session.query(CalendarEvent)
                .filter(
                    CalendarEvent.start_time < end,
                    CalendarEvent.end_time > start,
                    CalendarEvent.status != TaskStatus.CANCELLED,
                )
                .order_by(CalendarEvent.start_time)
                .all()
            )

            return [
                {
                    "id": e.id,
                    "title": e.title,
                    "start": e.start_time.strftime("%Y-%m-%d %H:%M"),
                    "end": e.end_time.strftime("%Y-%m-%d %H:%M"),
                    "location": e.location or "",
                    "description": e.description or "",
                }
                for e in events
            ]

    async def _save_event(
        self,
        title: str,
        start_time: datetime,
        end_time: datetime,
        location: Optional[str] = None,
        description: Optional[str] = None,
    ) -> int:
        """Сохранить событие в БД."""
        with self._session_factory() as session:
            from pds_ultimate.core.database import CalendarEvent, TaskStatus

            event = CalendarEvent(
                title=title,
                start_time=start_time,
                end_time=end_time,
                location=location,
                description=description,
                status=TaskStatus.PENDING,
            )
            session.add(event)
            session.commit()

            event_id = event.id
            logger.info(
                f"Calendar event created: #{event_id} '{title}' "
                f"{start_time.strftime('%Y-%m-%d %H:%M')}"
            )
            return event_id

    # ═══════════════════════════════════════════════════════════════════════
    # Напоминания за 30 минут
    # ═══════════════════════════════════════════════════════════════════════

    async def get_upcoming_reminders(self) -> list[dict]:
        """
        Получить события, до которых осталось <= reminder_minutes.
        Вызывается ежеминутно планировщиком.
        Возвращает список событий для напоминания.
        """
        now = datetime.now()

        with self._session_factory() as session:
            from pds_ultimate.core.database import CalendarEvent, TaskStatus

            # Все PENDING события, которые ещё не начались
            events = (
                session.query(CalendarEvent)
                .filter(
                    CalendarEvent.start_time > now,
                    CalendarEvent.status == TaskStatus.PENDING,
                )
                .all()
            )

            reminders = []
            for evt in events:
                minutes_until = (evt.start_time - now).total_seconds() / 60
                # Напоминаем когда до события осталось <= reminder_minutes
                # но > 0 (ещё не началось)
                if 0 < minutes_until <= evt.reminder_minutes:
                    reminders.append({
                        "id": evt.id,
                        "title": evt.title,
                        "start": evt.start_time.strftime("%Y-%m-%d %H:%M"),
                        "end": evt.end_time.strftime("%Y-%m-%d %H:%M"),
                        "location": evt.location or "",
                        "minutes_until": int(minutes_until),
                    })

            return reminders

    async def mark_reminded(self, event_id: int) -> None:
        """Пометить событие как 'напомнено' (перевести в IN_PROGRESS)."""
        with self._session_factory() as session:
            from pds_ultimate.core.database import CalendarEvent, TaskStatus

            event = session.query(CalendarEvent).filter(
                CalendarEvent.id == event_id,
            ).first()
            if event and event.status == TaskStatus.PENDING:
                event.status = TaskStatus.IN_PROGRESS
                session.commit()
                logger.info(f"Event #{event_id} marked as reminded")

    def format_reminder(self, reminder: dict) -> str:
        """Отформатировать напоминание для отправки."""
        parts = [
            f"⏰ Через {reminder['minutes_until']} мин:",
            f"📅 {reminder['title']}",
            f"🕐 {reminder['start'][-5:]}–{reminder['end'][-5:]}",
        ]
        if reminder.get("location"):
            parts.append(f"📍 {reminder['location']}")
        return "\n".join(parts)
