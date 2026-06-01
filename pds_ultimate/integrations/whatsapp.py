"""
PDS-Ultimate WhatsApp Integration (Green-API)
================================================
Интеграция с WhatsApp через Green-API (REST API).

По ТЗ:
- 3 последних активных чата для анализа стиля
- Чтение исходящих сообщений владельца
- Green-API — облачный сервис, не нужен браузер
- Требует авторизацию через QR-код в консоли Green-API
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import httpx

from pds_ultimate.config import config, logger


class WhatsAppClient:
    """
    Клиент WhatsApp через Green-API (REST).

    Жизненный цикл:
        client = WhatsAppClient()
        await client.start()       # Проверяет авторизацию
        messages = await client.get_recent_messages(chat_id, limit=100)
        await client.stop()        # Закрывает HTTP клиент
    """

    def __init__(self):
        self._http: Optional[httpx.AsyncClient] = None
        self._started = False
        self._instance_id = ""
        self._api_token = ""
        self._base_url = ""

    async def start(self) -> None:
        """Инициализировать клиент и проверить авторизацию."""
        if self._started:
            return

        if not config.whatsapp.enabled:
            logger.warning("WhatsApp отключён (WA_ENABLED=false)")
            return

        self._instance_id = config.whatsapp.green_api_instance
        self._api_token = config.whatsapp.green_api_token

        if not self._instance_id or not self._api_token:
            logger.error(
                "Green-API не настроен: "
                "задайте WA_GREEN_API_INSTANCE и WA_GREEN_API_TOKEN в .env"
            )
            return

        self._base_url = (
            f"https://7103.api.greenapi.com"
            f"/waInstance{self._instance_id}"
        )

        # Прокси для обхода блокировок
        proxy_url = config.telegram.proxy if hasattr(
            config, 'telegram') else ""
        http_kwargs: dict = {"timeout": 30.0}
        if proxy_url:
            import httpx as _hx
            _maj, _min = (int(x) for x in _hx.__version__.split(".")[:2])
            http_kwargs["proxy" if (_maj, _min) >= (0, 28) else "proxies"] = proxy_url
        self._http = httpx.AsyncClient(**http_kwargs)

        # Проверяем статус авторизации
        authorized = await self.is_logged_in()
        if not authorized:
            logger.warning(
                "⚠️ WhatsApp Green-API: Status = Not Authorized!\n"
                "   Зайди в console.green-api.com → "
                "Link with QR code → отсканируй QR телефоном"
            )
        else:
            logger.info("✅ WhatsApp Green-API: авторизован и готов")

        self._started = True
        logger.info("WhatsApp Green-API клиент запущен")

    async def stop(self) -> None:
        """Закрыть HTTP клиент."""
        if self._http:
            try:
                await self._http.aclose()
            except Exception:
                pass
        self._http = None
        self._started = False
        logger.info("WhatsApp Green-API клиент остановлен")

    async def is_logged_in(self) -> bool:
        """Проверить авторизацию через Green-API."""
        if not self._http:
            return False

        try:
            resp = await self._http.get(
                f"{self._base_url}/getStateInstance/{self._api_token}"
            )
            data = resp.json()
            state = data.get("stateInstance", "")
            return state == "authorized"
        except Exception as e:
            logger.error(f"Ошибка проверки статуса WA: {e}")
            return False

    async def get_recent_chats(self, limit: int = 3) -> list[dict]:
        """
        Получить последние активные чаты.

        Returns:
            [{"id": "79001234567@c.us", "name": "Имя контакта"}, ...]
        """
        if not self._started or not self._http:
            return []

        try:
            resp = await self._http.get(
                f"{self._base_url}/getChats/{self._api_token}"
            )
            data = resp.json()

            chats = []
            for chat in data[:limit]:
                chat_id = chat.get("id", "")
                name = chat.get("name", "") or chat_id
                if chat_id and "@c.us" in chat_id:  # Только личные чаты
                    chats.append({"id": chat_id, "name": name})

            logger.info(f"WhatsApp: найдено {len(chats)} чатов")
            return chats

        except Exception as e:
            logger.error(f"Ошибка получения чатов WA: {e}")
            return []

    async def get_recent_messages(
        self,
        chat_id: str,
        limit: int = 100,
        outgoing_only: bool = True,
    ) -> list[dict]:
        """
        Получить последние сообщения из чата через Green-API.

        Args:
            chat_id: ID чата (например "79001234567@c.us")
            limit: Максимум сообщений
            outgoing_only: Только исходящие (для анализа стиля)

        Returns:
            [{"text": "...", "timestamp": 1234567890, "is_outgoing": True}, ...]
        """
        if not self._started or not self._http:
            return []

        try:
            resp = await self._http.post(
                f"{self._base_url}/getChatHistory/{self._api_token}",
                json={"chatId": chat_id, "count": limit},
            )
            data = resp.json()

            messages = []
            for msg in data:
                msg_type = msg.get("type", "")
                # Только текстовые
                if msg_type not in ("outgoing", "incoming"):
                    continue

                is_outgoing = msg_type == "outgoing"
                if outgoing_only and not is_outgoing:
                    continue

                text = msg.get("textMessage", "") or ""
                if not text:
                    # Попробуем extendedTextMessage
                    ext = msg.get("extendedTextMessageData", {})
                    text = ext.get("text", "") if ext else ""

                if text:
                    messages.append({
                        "id": msg.get("idMessage", ""),
                        "text": text.strip(),
                        "is_outgoing": is_outgoing,
                        "timestamp": msg.get("timestamp", 0),
                    })

            logger.info(
                f"WhatsApp: {len(messages)} сообщений из чата '{chat_id}'"
            )
            return messages

        except Exception as e:
            logger.error(f"Ошибка чтения сообщений WA '{chat_id}': {e}")
            return []

    async def send_file(
        self,
        chat_id: str,
        file_path: str,
        caption: str = "",
        quoted_message_id: str | None = None,
    ) -> bool:
        """Отправить файл/фото через Green-API."""
        if not self._started or not self._http:
            return False
        path = Path(file_path)
        if not path.is_file():
            logger.error(f"WA send_file: файл не найден {file_path}")
            return False
        try:
            data: dict = {"chatId": chat_id}
            if caption:
                data["caption"] = caption
            if quoted_message_id:
                data["quotedMessageId"] = quoted_message_id
            with path.open("rb") as fh:
                resp = await self._http.post(
                    f"{self._base_url}/sendFileByUpload/{self._api_token}",
                    data=data,
                    files={"file": (path.name, fh, "application/octet-stream")},
                )
            success = resp.status_code == 200 and "idMessage" in resp.json()
            if success:
                logger.info(f"WhatsApp: файл отправлен в {chat_id}")
            return success
        except Exception as e:
            logger.error(f"Ошибка отправки WA файла: {e}")
            return False

    async def send_message(
        self, chat_id: str, text: str, quoted_message_id: str | None = None
    ) -> bool:
        """Отправить текстовое сообщение (с опциональным reply на сообщение)."""
        if not self._started or not self._http:
            return False

        try:
            payload: dict = {"chatId": chat_id, "message": text}
            if quoted_message_id:
                payload["quotedMessageId"] = quoted_message_id
            resp = await self._http.post(
                f"{self._base_url}/sendMessage/{self._api_token}",
                json=payload,
            )
            data = resp.json()
            success = "idMessage" in data
            if success:
                logger.info(f"WhatsApp: сообщение отправлено в {chat_id}")
            return success
        except Exception as e:
            logger.error(f"Ошибка отправки WA сообщения: {e}")
            return False

    async def get_style_messages(self) -> list[str]:
        """
        Собрать исходящие сообщения из N чатов для анализа стиля.
        По ТЗ: 3 чата, 100 сообщений из каждого.
        """
        if not self._started:
            logger.warning("WhatsApp не запущен")
            return []

        if not await self.is_logged_in():
            logger.warning(
                "WhatsApp не авторизован — "
                "отсканируй QR в console.green-api.com"
            )
            return []

        all_messages: list[str] = []
        chat_count = config.whatsapp.style_analysis_chat_count
        msg_limit = config.whatsapp.messages_per_chat

        chats = await self.get_recent_chats(limit=chat_count)

        for chat in chats:
            messages = await self.get_recent_messages(
                chat["id"], limit=msg_limit, outgoing_only=True,
            )
            for msg in messages:
                if msg.get("text"):
                    all_messages.append(msg["text"])

        logger.info(
            f"WhatsApp: собрано {len(all_messages)} сообщений "
            f"из {len(chats)} чатов для анализа стиля"
        )
        return all_messages

    # ═══════════════════════════════════════════════════════════════════════
    # Авто-ответ в стиле пользователя
    # ═══════════════════════════════════════════════════════════════════════

    async def poll_and_auto_reply(
        self,
        style_guide: str = "",
        poll_interval: float = 5.0,
    ) -> None:
        """
        Длительный polling входящих сообщений через Green-API receiveNotification.
        При получении входящего — генерирует ответ в стиле пользователя и отправляет.

        Предназначен для запуска как asyncio.Task.
        """
        if not self._started or not self._http:
            logger.warning("WhatsApp: авто-ответ невозможен — клиент не запущен")
            return

        logger.info("WhatsApp: запуск авто-ответного polling...")
        import asyncio

        while True:
            try:
                # Получаем одно уведомление из очереди
                resp = await self._http.get(
                    f"{self._base_url}/receiveNotification/{self._api_token}",
                    timeout=30.0,
                )
                data = resp.json()
                if not data:
                    await asyncio.sleep(poll_interval)
                    continue

                receipt_id = data.get("receiptId")
                body = data.get("body", {})
                msg_type = body.get("typeWebhook", "")

                if msg_type == "incomingMessageReceived":
                    await self._handle_incoming_wa(body, style_guide)

                # Удаляем уведомление из очереди
                if receipt_id:
                    await self._http.delete(
                        f"{self._base_url}/deleteNotification/{self._api_token}/{receipt_id}"
                    )

            except Exception as e:
                logger.warning(f"WhatsApp polling error: {e}")
                await asyncio.sleep(poll_interval)

    async def _handle_incoming_wa(self, body: dict, style_guide: str) -> None:
        """Обработать входящее WA сообщение и отправить авто-ответ."""
        try:
            msg_data = body.get("messageData", {})
            text = (
                msg_data.get("textMessageData", {}).get("textMessage", "")
                or msg_data.get("extendedTextMessageData", {}).get("text", "")
            )
            if not text:
                return

            sender_id = body.get("senderData", {}).get("sender", "")
            if not sender_id:
                return

            # Не отвечаем на групповые и статусы
            if "@g.us" in sender_id or "status@broadcast" in sender_id:
                return

            from pds_ultimate.core.llm_engine import llm_engine
            system = (
                f"Ты пишешь ответ от лица пользователя в WhatsApp. "
                f"Стиль общения: {style_guide or 'коротко, дружелюбно, по делу'}\n"
                "Отвечай естественно, в тоне собеседника. "
                "Не раскрывай что ты ИИ. Пиши только текст ответа."
            )
            reply_text = await llm_engine.chat(
                message=f"Входящее сообщение в WhatsApp: «{text}»\nНапиши ответ:",
                system_prompt=system,
                task_type="simple_answer",
            )
            if reply_text:
                import asyncio
                await asyncio.sleep(2.0)  # естественная задержка
                await self.send_message(sender_id, reply_text)
                logger.info(
                    f"[WA AUTO-REPLY] {sender_id}: {text[:40]}... → {reply_text[:40]}..."
                )
        except Exception as e:
            logger.error(f"[WA AUTO-REPLY] Ошибка: {e}", exc_info=True)


# ─── Глобальный экземпляр ────────────────────────────────────────────────────

wa_client = WhatsAppClient()
