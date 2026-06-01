"""
PDS-Ultimate VIP Hub
=======================
Модуль фильтрации и приоритетов (White List).

По ТЗ:
- White List: приоритетные контакты (email, TG, WA)
- Smart Alert: сообщения от VIP → мгновенное саммари + предлагаемый ответ
- Управление VIP-листом через естественный язык
"""

from __future__ import annotations

from typing import Optional

from pds_ultimate.config import logger
from pds_ultimate.core.database import (
    VIPContact,
    VIPSource,
)
from pds_ultimate.core.llm_engine import llm_engine


class VIPHub:
    """
    Управление VIP-контактами и приоритетной фильтрацией.
    """

    def __init__(self, db_session_factory):
        self._session_factory = db_session_factory

    # ═══════════════════════════════════════════════════════════════════════
    # CRUD VIP-контактов
    # ═══════════════════════════════════════════════════════════════════════

    def add_vip(
        self,
        name: str,
        source: VIPSource,
        identifier: str,
        contact_id: Optional[int] = None,
    ) -> VIPContact:
        """Добавить контакт в VIP-список."""
        with self._session_factory() as session:
            # Проверяем дубликат
            existing = session.query(VIPContact).filter_by(
                source=source,
                source_identifier=identifier,
            ).first()

            if existing:
                existing.is_active = True
                existing.display_name = name
                session.commit()
                logger.info(f"VIP обновлён: {name} ({source.value})")
                return existing

            vip = VIPContact(
                contact_id=contact_id,
                source=source,
                source_identifier=identifier,
                display_name=name,
                is_active=True,
            )
            session.add(vip)
            session.commit()

            logger.info(f"VIP добавлен: {name} ({source.value}: {identifier})")
            return vip

    def remove_vip(self, name: str) -> bool:
        """Удалить контакт из VIP-списка (деактивация)."""
        with self._session_factory() as session:
            vips = session.query(VIPContact).filter(
                VIPContact.display_name.ilike(f"%{name}%"),
                VIPContact.is_active == True,
            ).all()

            if not vips:
                return False

            for vip in vips:
                vip.is_active = False

            session.commit()
            logger.info(f"VIP удалён: {name} ({len(vips)} записей)")
            return True

    def get_vip_list(self) -> list[dict]:
        """Получить активный VIP-список."""
        with self._session_factory() as session:
            vips = session.query(VIPContact).filter_by(
                is_active=True
            ).all()

            return [
                {
                    "id": v.id,
                    "name": v.display_name,
                    "source": v.source.value,
                    "identifier": v.source_identifier,
                }
                for v in vips
            ]

    def is_vip(self, source: VIPSource, identifier: str) -> Optional[VIPContact]:
        """Проверить является ли контакт VIP."""
        with self._session_factory() as session:
            return session.query(VIPContact).filter_by(
                source=source,
                source_identifier=identifier,
                is_active=True,
            ).first()

    # ═══════════════════════════════════════════════════════════════════════
    # Smart Alert
    # ═══════════════════════════════════════════════════════════════════════

    async def smart_alert(
        self,
        vip_name: str,
        message_text: str,
    ) -> dict:
        """
        Обработать сообщение от VIP-контакта.
        Возвращает: {"summary": "...", "suggested_reply": "...", "urgency": "..."}
        """
        prompt = (
            f"Получено сообщение от VIP-контакта «{vip_name}»:\n\n"
            f"«{message_text}»\n\n"
            f"Верни JSON:\n"
            f'{{"summary": "краткая суть (1 предложение)", '
            f'"suggested_reply": "предлагаемый ответ", '
            f'"urgency": "low/medium/high/critical"}}'
        )

        import json

        response = await llm_engine.chat(
            message=prompt,
            task_type="summarize",
            temperature=0.3,
            json_mode=True,
        )

        try:
            return json.loads(response)
        except Exception:
            return {
                "summary": f"Сообщение от {vip_name}",
                "suggested_reply": "",
                "urgency": "medium",
            }

    # ═══════════════════════════════════════════════════════════════════════
    # Форматирование
    # ═══════════════════════════════════════════════════════════════════════

    def format_vip_list(self) -> str:
        """Отформатировать VIP-список для вывода."""
        vips = self.get_vip_list()

        if not vips:
            return "VIP-список пуст."

        lines = ["👑 VIP-КОНТАКТЫ:\n"]
        source_emoji = {
            "telegram": "📱",
            "whatsapp": "💬",
            "email": "📧",
        }

        for v in vips:
            emoji = source_emoji.get(v["source"], "📌")
            lines.append(f"  {emoji} {v['name']} ({v['source']})")

        return "\n".join(lines)

    async def format_alert(self, vip_name: str, alert: dict) -> str:
        """Форматировать VIP-алерт для отправки владельцу."""
        urgency_emoji = {
            "low": "🟢",
            "medium": "🟡",
            "high": "🟠",
            "critical": "🔴",
        }

        emoji = urgency_emoji.get(alert.get("urgency", "medium"), "🟡")

        text = (
            f"{emoji} VIP-СООБЩЕНИЕ от {vip_name}\n\n"
            f"📝 Суть: {alert.get('summary', 'N/A')}\n"
        )

        if alert.get("suggested_reply"):
            text += f"\n💬 Предлагаемый ответ:\n«{alert['suggested_reply']}»"

        return text
