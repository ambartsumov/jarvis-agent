"""
PDS-Ultimate Auto Responder
===============================
Авто-ответчик с определением занятости из БД.

По ТЗ:
- Если занят → «Я на встрече до 15:00, отвечу позже»
- Генерация ответов в стиле владельца
- Почтовый агент: чтение + ответы Gmail в стиле владельца
- Календарь хранится в памяти (БД), НЕ Google Calendar
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pds_ultimate.core.llm_engine import llm_engine


class AutoResponder:
    """
    Авто-ответчик: генерация ответов от имени владельца.
    Определяет занятость по событиям в БД (без Google Calendar).
    """

    def __init__(self, db_session_factory):
        self._session_factory = db_session_factory

    # ═══════════════════════════════════════════════════════════════════════
    # Определение занятости
    # ═══════════════════════════════════════════════════════════════════════

    async def check_busy_status(self) -> Optional[dict]:
        """
        Проверить занятость владельца по событиям в БД.
        Возвращает текущее событие или None.
        """
        now = datetime.now()

        with self._session_factory() as session:
            from pds_ultimate.core.database import CalendarEvent, TaskStatus

            event = session.query(CalendarEvent).filter(
                CalendarEvent.start_time <= now,
                CalendarEvent.end_time > now,
                CalendarEvent.status == TaskStatus.PENDING,
            ).first()

            if event:
                return {
                    "title": event.title,
                    "end_time": event.end_time,
                    "location": event.location,
                }

        return None

    # ═══════════════════════════════════════════════════════════════════════
    # Генерация авто-ответов
    # ═══════════════════════════════════════════════════════════════════════

    async def generate_busy_reply(
        self,
        sender_name: str,
        message_text: str,
        busy_info: dict,
    ) -> str:
        """
        Сгенерировать ответ «занят» в стиле владельца.
        """
        end_time = busy_info.get("end_time")
        if isinstance(end_time, datetime):
            time_str = end_time.strftime("%H:%M")
        else:
            time_str = "позже"

        prompt = (
            f"Тебе написал {sender_name}: «{message_text}»\n"
            f"Ты сейчас на встрече «{busy_info.get('title', '')}» до {time_str}.\n"
            f"Ответь коротко что занят и ответишь после встречи. "
            f"Пиши в стиле владельца (неформально, кратко)."
        )

        return await llm_engine.generate_in_style(prompt, sender_name)

    async def generate_reply(
        self,
        sender_name: str,
        message_text: str,
        context: Optional[str] = None,
    ) -> str:
        """
        Сгенерировать ответ в стиле владельца на произвольное сообщение.
        """
        prompt = f"Тебе написал {sender_name}: «{message_text}»\nОтветь в стиле владельца."

        if context:
            prompt += f"\nКонтекст: {context}"

        return await llm_engine.generate_in_style(prompt, sender_name)

    # ═══════════════════════════════════════════════════════════════════════
    # Gmail авто-ответчик
    # ═══════════════════════════════════════════════════════════════════════

    async def process_email(
        self,
        sender: str,
        subject: str,
        body: str,
    ) -> dict:
        """
        Обработать входящее письмо: саммари + предлагаемый ответ.
        Возвращает: {"summary": "...", "draft_reply": "...", "priority": "..."}
        """
        import json

        prompt = (
            f"Входящее письмо:\n"
            f"От: {sender}\n"
            f"Тема: {subject}\n"
            f"Текст: {body[:3000]}\n\n"
            f"Верни JSON:\n"
            f'{{"summary": "краткая суть", '
            f'"draft_reply": "черновик ответа в стиле владельца", '
            f'"priority": "low/medium/high", '
            f'"action_needed": true/false}}'
        )

        response = await llm_engine.chat(
            message=prompt,
            task_type="summarize",
            temperature=0.4,
            json_mode=True,
        )

        try:
            return json.loads(response)
        except Exception:
            return {
                "summary": f"Письмо от {sender}: {subject}",
                "draft_reply": "",
                "priority": "medium",
                "action_needed": True,
            }
