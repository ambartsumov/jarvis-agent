"""
Тесты Google Calendar Service — integrations/google_calendar.py
"""

from datetime import datetime


class TestCalendarEvent:
    """Тесты CalendarEvent."""

    def test_import(self):
        """Модуль импортируется."""
        from pds_ultimate.integrations.google_calendar import (
            GoogleCalendarService,
            google_calendar,
        )
        assert GoogleCalendarService is not None
        assert google_calendar is not None

    def test_event_creation(self):
        """CalendarEvent создаётся."""
        from pds_ultimate.integrations.google_calendar import CalendarEvent

        event = CalendarEvent(
            summary="Тестовая встреча",
            start=datetime(2025, 6, 15, 10, 0),
            end=datetime(2025, 6, 15, 11, 0),
            description="Описание",
        )
        assert event.summary == "Тестовая встреча"
        assert event.start == datetime(2025, 6, 15, 10, 0)
        assert event.end == datetime(2025, 6, 15, 11, 0)

    def test_event_default_end(self):
        """CalendarEvent: end по умолчанию None."""
        from pds_ultimate.integrations.google_calendar import CalendarEvent

        event = CalendarEvent(
            summary="Событие",
            start=datetime(2025, 6, 15, 10, 0),
        )
        assert event.end is None

    def test_event_slots_based(self):
        """CalendarEvent использует __slots__ или атрибуты."""
        from pds_ultimate.integrations.google_calendar import CalendarEvent

        event = CalendarEvent(
            summary="Test",
            start=datetime.now(),
        )
        assert hasattr(event, "summary")
        assert hasattr(event, "start")

    def test_event_with_id(self):
        """CalendarEvent с ID."""
        from pds_ultimate.integrations.google_calendar import CalendarEvent

        event = CalendarEvent(
            summary="Test",
            start=datetime.now(),
            id="abc123",
        )
        assert event.id == "abc123"


class TestConflictInfo:
    """Тесты ConflictInfo."""

    def test_creation(self):
        """ConflictInfo создаётся."""
        from pds_ultimate.integrations.google_calendar import (
            CalendarEvent,
            ConflictInfo,
        )

        e1 = CalendarEvent(
            summary="Meeting 1", start=datetime(2025, 6, 15, 10, 0)
        )
        e2 = CalendarEvent(
            summary="Meeting 2", start=datetime(2025, 6, 15, 10, 30)
        )

        conflict = ConflictInfo(event_a=e1, event_b=e2, overlap_minutes=30)
        assert conflict.overlap_minutes == 30


class TestFreeSlot:
    """Тесты FreeSlot."""

    def test_creation(self):
        """FreeSlot создаётся."""
        from pds_ultimate.integrations.google_calendar import FreeSlot

        slot = FreeSlot(
            start=datetime(2025, 6, 15, 10, 0),
            end=datetime(2025, 6, 15, 11, 0),
        )
        assert slot.start < slot.end


class TestGoogleCalendarService:
    """Тесты сервиса."""

    def test_instance(self):
        """Глобальный экземпляр."""
        from pds_ultimate.integrations.google_calendar import google_calendar

        assert google_calendar is not None

    def test_service_creation(self):
        """Сервис создаётся."""
        from pds_ultimate.integrations.google_calendar import (
            GoogleCalendarService,
        )

        service = GoogleCalendarService()
        assert service is not None

    def test_format_events_list_empty(self):
        """format_events_list с пустым списком."""
        from pds_ultimate.integrations.google_calendar import (
            GoogleCalendarService,
        )

        service = GoogleCalendarService()
        text = service.format_events_list([])
        assert isinstance(text, str)
        # Пустой список — информативное сообщение
        assert len(text) > 0

    def test_format_events_list_with_events(self):
        """format_events_list с событиями."""
        from pds_ultimate.integrations.google_calendar import (
            CalendarEvent,
            GoogleCalendarService,
        )

        service = GoogleCalendarService()
        events = [
            CalendarEvent(
                summary="Встреча с партнёром",
                start=datetime(2025, 6, 15, 10, 0),
                end=datetime(2025, 6, 15, 11, 0),
            ),
            CalendarEvent(
                summary="Обед",
                start=datetime(2025, 6, 15, 13, 0),
                end=datetime(2025, 6, 15, 14, 0),
            ),
        ]
        text = service.format_events_list(events)
        assert "Встреча с партнёром" in text
        assert "Обед" in text

    def test_format_day_summary(self):
        """format_day_summary."""
        from pds_ultimate.integrations.google_calendar import (
            CalendarEvent,
            GoogleCalendarService,
        )

        service = GoogleCalendarService()
        events = [
            CalendarEvent(
                summary="Звонок",
                start=datetime(2025, 6, 15, 9, 0),
            )
        ]
        text = service.format_day_summary(events)
        assert isinstance(text, str)
        assert len(text) > 0  # хоть что-то вернёт

    def test_check_conflicts_no_overlap(self):
        """check_conflicts: нет пересечений."""
        from pds_ultimate.integrations.google_calendar import (
            CalendarEvent,
            GoogleCalendarService,
        )

        service = GoogleCalendarService()
        new_event = CalendarEvent(
            summary="A",
            start=datetime(2025, 6, 15, 9, 0),
            end=datetime(2025, 6, 15, 10, 0),
        )
        existing = [
            CalendarEvent(
                summary="B",
                start=datetime(2025, 6, 15, 11, 0),
                end=datetime(2025, 6, 15, 12, 0),
            ),
        ]
        conflicts = service.check_conflicts(new_event, existing)
        assert len(conflicts) == 0

    def test_check_conflicts_with_overlap(self):
        """check_conflicts: есть пересечение."""
        from pds_ultimate.integrations.google_calendar import (
            CalendarEvent,
            GoogleCalendarService,
        )

        service = GoogleCalendarService()
        new_event = CalendarEvent(
            summary="A",
            start=datetime(2025, 6, 15, 9, 0),
            end=datetime(2025, 6, 15, 10, 30),
        )
        existing = [
            CalendarEvent(
                summary="B",
                start=datetime(2025, 6, 15, 10, 0),
                end=datetime(2025, 6, 15, 11, 0),
            ),
        ]
        conflicts = service.check_conflicts(new_event, existing)
        assert len(conflicts) == 1
        assert conflicts[0].overlap_minutes == 30

    def test_get_busy_message(self):
        """get_busy_message."""
        from pds_ultimate.integrations.google_calendar import (
            CalendarEvent,
            GoogleCalendarService,
        )

        service = GoogleCalendarService()
        event = CalendarEvent(
            summary="Переговоры",
            start=datetime(2025, 6, 15, 14, 0),
            end=datetime(2025, 6, 15, 15, 0),
        )
        msg = service.get_busy_message(event)
        assert isinstance(msg, str)
        assert "15:00" in msg

    def test_find_free_slots(self):
        """find_free_slots возвращает список."""
        from pds_ultimate.integrations.google_calendar import (
            GoogleCalendarService,
        )

        service = GoogleCalendarService()
        # find_free_slots is sync, takes (events, ..., reference_date=...)
        slots = service.find_free_slots(
            events=[],
            reference_date=datetime.now(),
        )
        assert isinstance(slots, list)
