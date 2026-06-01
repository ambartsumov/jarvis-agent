"""
PDS-Ultimate Telethon Integration
=======================================
Userbot через Telethon для анализа стиля.

По ТЗ:
- 7 чатов Telegram для анализа стиля
- Чтение истории сообщений
- Анализ стиля переписки владельца
- Сбор данных для StyleAnalyzer
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from pds_ultimate.config import config, logger


class TelethonClient:
    """
    Userbot для анализа стиля переписки.

    Жизненный цикл:
        client = TelethonClient()
        await client.start()          # Авторизация (телефон + код)
        msgs = await client.get_messages("username", 100)
        await client.scan_for_style()
        await client.stop()
    """

    def __init__(self):
        self._client = None
        self._started = False
        self._auto_reply_enabled = False
        self._auto_reply_handler = None
        self._style_guide: str = ""
        self._incoming_listener_registered = False

    async def start(self) -> None:
        """Запуск Telethon клиента."""
        if self._started:
            return

        if not config.telethon.api_id or not config.telethon.api_hash:
            logger.warning(
                "Telethon: api_id/api_hash не заданы — клиент не запущен"
            )
            return

        try:
            import python_socks
            from telethon import TelegramClient
            from telethon.sessions import StringSession

            # Прокси для обхода блокировок
            # Telethon использует MTProto (TCP) — нужен SOCKS5, НЕ HTTP
            # HTTP прокси (порт 10809) не работает для MTProto
            # SOCKS5 обычно на порту 10808 (V2Ray/Clash стандарт)
            proxy = None
            if config.telegram.proxy:
                from urllib.parse import urlparse
                parsed = urlparse(config.telegram.proxy)
                host = parsed.hostname or "127.0.0.1"
                # Переключаемся на SOCKS5 порт (10808 для V2Ray)
                socks_port = (parsed.port or 10809) - 1  # 10809 → 10808
                # Используем прокси только если SOCKS-порт реально доступен,
                # иначе подключаемся к Telegram напрямую (устойчивость).
                import socket as _socket
                try:
                    with _socket.create_connection((host, socks_port), timeout=1.5):
                        proxy = (python_socks.ProxyType.SOCKS5, host, socks_port)
                        logger.info(f"Telethon SOCKS5 proxy: {host}:{socks_port}")
                except OSError:
                    logger.warning(
                        f"Telethon: SOCKS прокси {host}:{socks_port} недоступен — напрямую"
                    )

            # StringSession исключает блокировки SQLite при нескольких процессах
            if config.telethon.session_string:
                session = StringSession(config.telethon.session_string)
                logger.info("Telethon: используется StringSession (без файла)")
            else:
                session = config.telethon.session_name

            self._client = TelegramClient(
                session,
                config.telethon.api_id,
                config.telethon.api_hash,
                proxy=proxy,
            )

            # Сначала пробуем connect — если сессия есть, код не нужен
            await self._client.connect()

            if await self._client.is_user_authorized():
                me = await self._client.get_me()
                self._started = True
                logger.info(
                    f"Telethon подключён (сессия): "
                    f"{me.first_name} {me.last_name or ''} "
                    f"(@{me.username or 'N/A'})"
                )
            else:
                # Сессия не авторизована — НЕ запрашиваем код интерактивно.
                # Запустите отдельно: python agent/telethon_auth.py
                logger.warning(
                    "Telethon: сессия не авторизована. "
                    "Запустите 'python telethon_auth.py' для первичной авторизации."
                )
                await self._client.disconnect()

        except Exception as e:
            logger.error(f"Ошибка запуска Telethon: {e}", exc_info=True)

    async def stop(self) -> None:
        """Остановка клиента."""
        if self._client:
            try:
                await self._client.disconnect()
            except Exception:
                pass
        self._client = None
        self._started = False
        logger.info("Telethon отключён")

    async def _ensure_connected(self) -> bool:
        """
        Убедиться что Telethon подключён. Автоматически переподключается.
        Возвращает True если соединение есть или успешно восстановлено.
        """
        if not self._client:
            return False
        try:
            if not self._client.is_connected():
                logger.info("Telethon: переподключение...")
                await self._client.connect()
                if not await self._client.is_user_authorized():
                    self._started = False
                    logger.warning("Telethon: переподключение — сессия устарела")
                    return False
                self._started = True
                logger.info("Telethon: переподключение успешно")
            return True
        except Exception as e:
            logger.warning(f"Telethon: ошибка переподключения: {e}")
            return False

    async def send_message(
        self, target: str | int, text: str, reply_to: int | None = None
    ) -> bool:
        """
        Отправить сообщение через Telethon userbot.

        Args:
            target: username (@aynur16bkm), телефон (+7...) или chat_id
            text: Текст сообщения
            reply_to: id сообщения, на которое отвечаем (reply в мессенджере)

        Returns:
            True при успехе
        """
        if not self._started:
            raise RuntimeError("Telethon userbot не запущен")

        if not await self._ensure_connected():
            raise RuntimeError("Telethon не удалось подключиться")

        if isinstance(target, str) and not target.startswith("@"):
            # Добавляем @ для username (если не начинается с + или цифры)
            if not target.lstrip("+").isdigit():
                target = f"@{target}"

        await self._client.send_message(target, text, reply_to=reply_to)
        logger.info(f"Telethon: сообщение отправлено → {target}" + (f" (reply→{reply_to})" if reply_to else ""))
        return True

    async def send_file(
        self,
        target: str | int,
        file_path: str,
        caption: str = "",
        reply_to: int | None = None,
    ) -> bool:
        """Отправить фото/файл через userbot."""
        if not self._started:
            raise RuntimeError("Telethon userbot не запущен")
        if not await self._ensure_connected():
            raise RuntimeError("Telethon не удалось подключиться")
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Файл не найден: {file_path}")

        if isinstance(target, str) and not target.startswith("@"):
            if not target.lstrip("+").isdigit():
                target = f"@{target}"

        await self._client.send_file(
            target, str(path), caption=caption or None, reply_to=reply_to,
        )
        logger.info(f"Telethon: файл отправлен → {target}: {path.name}")
        return True

    # ═══════════════════════════════════════════════════════════════════════
    # Транскрибация голосовых / кружков из чатов
    # ═══════════════════════════════════════════════════════════════════════

    async def _transcribe_media(self, message) -> str | None:
        """
        Скачать голосовое / видео-кружок из Telethon message и транскрибировать.

        Поддерживает:
        - message.voice  (голосовое сообщение)
        - message.video_note  (видео-кружок)

        Returns:
            Распознанный текст или None если не удалось.
        """
        if not self._client:
            return None

        # Определяем тип медиа
        from telethon.tl.types import (
            DocumentAttributeAudio,
            DocumentAttributeVideo,
        )

        media = message.media
        if not media:
            return None

        # Определяем расширение файла
        is_voice = False
        is_video_note = False
        duration = 0

        if hasattr(media, "document") and media.document:
            doc = media.document
            for attr in (doc.attributes or []):
                if isinstance(attr, DocumentAttributeAudio) and getattr(attr, "voice", False):
                    is_voice = True
                    duration = getattr(attr, "duration", 0)
                    break
                if isinstance(attr, DocumentAttributeVideo) and getattr(attr, "round_message", False):
                    is_video_note = True
                    duration = getattr(attr, "duration", 0)
                    break

        if not is_voice and not is_video_note:
            return None

        # Скачиваем файл
        ext = ".ogg" if is_voice else ".mp4"
        media_type = "голосовое" if is_voice else "видео-кружок"
        tmp_dir = tempfile.mkdtemp(prefix="pds_telethon_voice_")
        file_path = Path(tmp_dir) / f"media{ext}"

        try:
            await self._client.download_media(message, file=str(file_path))

            if not file_path.exists() or file_path.stat().st_size == 0:
                logger.warning(f"Telethon: скачанный файл пуст или не существует")
                return None

            logger.info(
                f"Telethon: {media_type} скачано, "
                f"размер: {file_path.stat().st_size} байт, "
                f"длительность: {duration}с"
            )

            # Транскрибируем через SpeechEngine
            from pds_ultimate.core.speech_engine import speech_engine

            text = speech_engine.transcribe(str(file_path))

            if text and text.strip():
                logger.info(
                    f"Telethon: {media_type} распознано ({duration}с): "
                    f"«{text[:80]}...»"
                )
                return text.strip()
            else:
                logger.info(f"Telethon: {media_type} — не удалось распознать речь")
                return None

        except Exception as e:
            logger.error(f"Telethon: ошибка транскрибации {media_type}: {e}", exc_info=True)
            return None
        finally:
            # Очистка временных файлов
            try:
                if file_path.exists():
                    os.remove(file_path)
            except OSError:
                pass
            try:
                os.rmdir(tmp_dir)
            except OSError:
                pass

    # ═══════════════════════════════════════════════════════════════════════
    # Живой слушатель входящих сообщений
    # ═══════════════════════════════════════════════════════════════════════

    async def enable_message_listener(self) -> bool:
        """
        Подписаться на входящие сообщения Telegram (Telethon userbot).

        Все новые сообщения из личных чатов и групп передаются в
        ProactiveEngine.filter_incoming_message — там решается,
        нужно ли уведомить владельца.

        Поддерживает:
        - Текстовые сообщения
        - Голосовые сообщения (voice) → транскрибация → обработка как текст
        - Видео-кружки (video_note) → транскрибация → обработка как текст

        Возвращает True если успешно подписались, False если Telethon не запущен.
        """
        if not self._started or not self._client:
            logger.warning("Telethon: нельзя включить слушатель — клиент не запущен")
            return False

        try:
            from telethon import events

            @self._client.on(events.NewMessage(incoming=True))
            async def _on_new_message(event):
                try:
                    # Игнорируем исходящие (от себя)
                    if event.out:
                        return

                    # ── Фильтр каналов ──────────────────────────────────
                    # Каналы (broadcasts) — игнорируем полностью.
                    # Только личные сообщения (is_private) обрабатываются.
                    if getattr(event, "is_channel", False):
                        return
                    if not getattr(event, "is_private", True):
                        # Сообщения из групп тоже пропускаем,
                        # оставляем только личку
                        return

                    # ── Фильтр наших собственных ботов ──────────────────
                    # Telegram-боты (is_bot=True) игнорируем, иначе бот
                    # видит собственные ответы как «входящие» → каскад дублей.
                    try:
                        _sender_peek = await event.get_sender()
                        if _sender_peek and getattr(_sender_peek, "bot", False):
                            return
                    except Exception:
                        pass

                    text = getattr(event.message, "text", "") or ""
                    is_voice_transcribed = False

                    # ── Голосовые / кружки → транскрибация ────────────────
                    if not text:
                        transcribed = await self._transcribe_media(event.message)
                        if transcribed:
                            # Определяем тип медиа для лога
                            from telethon.tl.types import (
                                DocumentAttributeAudio,
                                DocumentAttributeVideo,
                            )
                            media_label = "голосовое"
                            if event.message.media and hasattr(event.message.media, "document"):
                                doc = event.message.media.document
                                for attr in (doc.attributes or []):
                                    if isinstance(attr, DocumentAttributeVideo) and getattr(attr, "round_message", False):
                                        media_label = "видео-кружок"
                                        break
                            text = f"[{media_label}]: {transcribed}"
                            is_voice_transcribed = True
                        else:
                            # Ни текста, ни голосового/кружка
                            return

                    # ── Отправитель ──────────────────────────────────────
                    sender_name = ""
                    sender_username = ""
                    try:
                        sender = await event.get_sender()
                        if sender:
                            fn = getattr(sender, "first_name", "") or ""
                            ln = getattr(sender, "last_name", "") or ""
                            sender_name = f"{fn} {ln}".strip()
                            sender_username = getattr(sender, "username", "") or ""
                            if not sender_name:
                                sender_name = sender_username
                    except Exception:
                        pass

                    chat_id = event.chat_id or 0

                    # ── Текст сообщения, на которое ответили (reply-to) ───
                    reply_to_text = ""
                    if event.reply_to:
                        try:
                            replied_msg = await event.get_reply_message()
                            if replied_msg:
                                reply_to_text = getattr(replied_msg, "text", "") or ""
                        except Exception:
                            pass

                    # ── AutoDialogue: авто-ответ если диалог активен ──────
                    from pds_ultimate.core.auto_dialogue import auto_dialogue_manager
                    auto_reply = await auto_dialogue_manager.process_incoming(
                        text=text,
                        sender_username=sender_username,
                        sender_name=sender_name,
                        chat_id=chat_id,
                        reply_to_text=reply_to_text,
                    )
                    if auto_reply:
                        try:
                            await self._client.send_message(chat_id, auto_reply)
                            logger.info(
                                f"AutoDialogue: ✉️ авто-ответ отправлен → "
                                f"{sender_username or chat_id}"
                            )
                        except Exception as send_err:
                            logger.warning(f"AutoDialogue: ошибка отправки: {send_err}")
                        # Не передаём в ProactiveEngine — уже обработали
                        return

                    # ── ProactiveEngine: уведомить владельца если важно ───
                    from pds_ultimate.core.proactive_engine import proactive_engine
                    important_event = await proactive_engine.filter_incoming_message(
                        text=text,
                        chat_id=chat_id,
                        sender_name=sender_name,
                    )
                    if important_event:
                        proactive_engine.add_event(important_event)

                except Exception as e:
                    logger.debug(f"Telethon listener error: {e}")

            logger.info("✅ Telethon: слушатель входящих сообщений включён")
            return True

        except Exception as e:
            logger.error(f"Ошибка включения Telethon слушателя: {e}")
            return False

    # ═══════════════════════════════════════════════════════════════════════
    # Polling-обход: проверяем активные диалоги вручную (резервный метод)
    # ═══════════════════════════════════════════════════════════════════════

    async def start_dialogue_poller(self, interval_sec: int = 30) -> None:
        """
        Фоновый поллинг активных диалогов.

        Каждые interval_sec секунд проходит по диалогам в auto_dialogue_manager
        и проверяет, есть ли новые сообщения через Telethon get_messages.
        Это резервный механизм на случай, если event-listener пропустит сообщения
        (прокси-пропасть, разрыв соединения и т.д.).
        """
        from pds_ultimate.core.auto_dialogue import auto_dialogue_manager

        # timestamp последней проверки для каждого chat_id
        last_checked: dict[int, float] = {}
        import time as _time

        logger.info("✅ Telethon: диалог-поллер запущен")

        while True:
            await asyncio.sleep(interval_sec)

            if not self._started or not self._client:
                continue

            try:
                active = list(auto_dialogue_manager._conversations.values())
                for conv in active:
                    if not conv.chat_id or not conv.auto_reply:
                        continue

                    since_ts = last_checked.get(conv.chat_id, conv.started_at)
                    last_checked[conv.chat_id] = _time.time()

                    try:
                        # Забираем последние 5 сообщений из чата
                        msgs = await self._client.get_messages(
                            conv.chat_id, limit=5
                        )
                        for msg in reversed(msgs):  # oldest first
                            if msg.out:
                                continue
                            # Пропускаем уже обработанные сообщения
                            msg_ts = msg.date.timestamp() if msg.date else 0
                            if msg_ts <= since_ts:
                                continue

                            text = getattr(msg, "text", "") or ""
                            if not text:
                                # Пробуем транскрибировать голосовое/кружок
                                transcribed = await self._transcribe_media(msg)
                                if transcribed:
                                    from telethon.tl.types import (
                                        DocumentAttributeVideo,
                                    )
                                    media_label = "голосовое"
                                    if msg.media and hasattr(msg.media, "document"):
                                        doc = msg.media.document
                                        for attr in (doc.attributes or []):
                                            if isinstance(attr, DocumentAttributeVideo) and getattr(attr, "round_message", False):
                                                media_label = "видео-кружок"
                                                break
                                    text = f"[{media_label}]: {transcribed}"
                                else:
                                    continue

                            # Получаем отправителя
                            sender_name = ""
                            sender_username = ""
                            try:
                                sender = await self._client.get_entity(msg.from_id) if msg.from_id else None
                                if sender:
                                    fn = getattr(sender, "first_name", "") or ""
                                    ln = getattr(sender, "last_name", "") or ""
                                    sender_name = f"{fn} {ln}".strip()
                                    sender_username = getattr(sender, "username", "") or ""
                            except Exception:
                                pass

                            auto_reply = await auto_dialogue_manager.process_incoming(
                                text=text,
                                sender_username=sender_username,
                                sender_name=sender_name,
                                chat_id=conv.chat_id,
                            )
                            if auto_reply:
                                await self._client.send_message(conv.chat_id, auto_reply)
                                logger.info(
                                    f"DialoguePoller: ✉️ ответ отправлен → "
                                    f"{sender_username or conv.chat_id}"
                                )
                    except Exception as e:
                        logger.debug(f"DialoguePoller: ошибка для chat_id={conv.chat_id}: {e}")

            except Exception as e:
                logger.debug(f"DialoguePoller: цикл ошибка: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # Чтение сообщений
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _describe_media(msg) -> str:
        """Human-readable placeholder for non-text messages."""
        try:
            from telethon.tl.types import (
                DocumentAttributeAudio,
                DocumentAttributeVideo,
                MessageMediaDocument,
                MessageMediaPhoto,
            )

            media = msg.media
            if isinstance(media, MessageMediaPhoto):
                return "[фото]" + (f": {msg.message}" if msg.message else "")
            if isinstance(media, MessageMediaDocument) and media.document:
                for attr in media.document.attributes or []:
                    if isinstance(attr, DocumentAttributeAudio) and getattr(attr, "voice", False):
                        return "[голосовое]"
                    if isinstance(attr, DocumentAttributeVideo) and getattr(attr, "round_message", False):
                        return "[кружок]"
                mime = getattr(media.document, "mime_type", "") or ""
                if mime.startswith("video/"):
                    return "[видео]"
                if mime.startswith("image/"):
                    return "[фото]"
                return "[файл]"
        except Exception:
            pass
        return "[медиа]"

    async def get_messages(
        self,
        chat_identifier: str,
        limit: int = 100,
        offset_days: int = 30,
    ) -> list[dict]:
        """
        Получить последние сообщения из чата.

        Args:
            chat_identifier: username, phone, или ID чата
            limit: Максимальное количество сообщений
            offset_days: За сколько дней брать (фильтр после получения)

        Returns:
            [{"text", "date", "from_id", "is_owner", "reply_to"}, ...]
        """
        if not self._started:
            logger.warning("Telethon не запущен — get_messages пропускается")
            return []

        if not await self._ensure_connected():
            logger.warning("Telethon не удалось подключиться — get_messages пропускается")
            return []

        try:
            # Resolve entity — try multiple methods
            entity = await self._resolve_entity(chat_identifier)
            if not entity:
                logger.warning(f"Не удалось найти чат: {chat_identifier}")
                return []

            me = await self._client.get_me()

            # Get latest messages WITHOUT offset_date
            # (offset_date in Telethon = messages OLDER than date, not newer)
            messages = await self._client.get_messages(
                entity,
                limit=limit,
            )

            # Filter by date range manually (offset_days=0 → без фильтра, вся выборка limit)
            if offset_days > 0:
                cutoff = datetime.utcnow() - timedelta(days=offset_days)
                cutoff = cutoff.replace(
                    tzinfo=messages[0].date.tzinfo) if messages and messages[0].date else cutoff
            else:
                cutoff = None

            result = []
            for msg in messages:
                text = (msg.text or msg.message or "").strip()
                if not text and msg.media:
                    text = self._describe_media(msg)

                if cutoff is not None and msg.date and msg.date.replace(tzinfo=None) < cutoff.replace(tzinfo=None):
                    continue

                if not text:
                    continue

                sender_name = ""
                try:
                    if msg.sender:
                        sender_name = getattr(
                            msg.sender, "first_name", "") or ""
                        last = getattr(msg.sender, "last_name", "") or ""
                        if last:
                            sender_name = f"{sender_name} {last}"
                except Exception:
                    pass

                result.append({
                    "id": msg.id,
                    "text": text,
                    "date": msg.date.isoformat() if msg.date else "",
                    "from_id": msg.sender_id,
                    "from_name": sender_name,
                    "is_owner": msg.sender_id == me.id,
                    "reply_to": msg.reply_to_msg_id,
                    "chat": str(chat_identifier),
                })

            logger.info(
                f"Telethon: получено {len(result)} сообщений "
                f"из {chat_identifier} (всего загружено {len(messages)})"
            )
            return result

        except Exception as e:
            logger.error(
                f"Ошибка чтения чата {chat_identifier}: {e}",
                exc_info=True,
            )
            return []

    async def _resolve_entity(self, identifier: str):
        """
        Умный поиск entity — пробует несколько методов.
        username, phone, id, поиск по имени в диалогах.
        """
        if not identifier:
            return None

        if not await self._ensure_connected():
            return None

        clean = identifier.lstrip("@")

        # 1. Try direct resolve (username, phone, numeric id)
        for variant in [identifier, f"@{clean}", clean]:
            try:
                return await self._client.get_entity(variant)
            except Exception:
                continue

        # 2. Try numeric ID
        try:
            num_id = int(identifier)
            return await self._client.get_entity(num_id)
        except (ValueError, Exception):
            pass

        # 3. Search in dialogs by name (fuzzy)
        try:
            search_lower = identifier.lower().replace("@", "")
            async for dialog in self._client.iter_dialogs(limit=200):
                name = (dialog.name or "").lower()
                if search_lower in name or name in search_lower:
                    logger.info(
                        f"Telethon: найден диалог '{dialog.name}' для '{identifier}'")
                    return dialog.entity
        except Exception as e:
            logger.warning(f"Telethon dialog search error: {e}")

        return None

    async def get_my_messages(
        self,
        chat_identifier: str,
        limit: int = 100,
    ) -> list[str]:
        """
        Получить только МОИ сообщения из чата.
        Для анализа стиля нужны только сообщения владельца.
        """
        all_msgs = await self.get_messages(chat_identifier, limit)
        return [m["text"] for m in all_msgs if m["is_owner"]]

    # ═══════════════════════════════════════════════════════════════════════
    # Сканирование для анализа стиля
    # ═══════════════════════════════════════════════════════════════════════

    async def scan_for_style(
        self,
        chats: Optional[list[str]] = None,
    ) -> dict[str, list[str]]:
        """
        Сканировать чаты для анализа стиля переписки.

        По ТЗ: 7 чатов Telegram, config.telethon.style_analysis_chat_count

        Args:
            chats: Список чатов (username/phone/id).
                   Если None — берём из конфига.

        Returns:
            {"chat_identifier": ["msg1", "msg2", ...], ...}
        """
        if not self._started:
            logger.warning("Telethon не запущен — scan_for_style пропускается")
            return {}

        if chats is None:
            chats = config.telethon.style_chats

        if not chats:
            logger.warning("Telethon: нет чатов для анализа стиля")
            return {}

        # Ограничиваем количество чатов
        max_chats = config.telethon.style_analysis_chat_count
        chats_to_scan = chats[:max_chats]
        msgs_per_chat = config.telethon.messages_per_chat

        result: dict[str, list[str]] = {}

        for chat_id in chats_to_scan:
            try:
                my_msgs = await self.get_my_messages(chat_id, msgs_per_chat)
                if my_msgs:
                    result[str(chat_id)] = my_msgs
                    logger.info(
                        f"  ✓ {chat_id}: {len(my_msgs)} сообщений владельца"
                    )
                else:
                    logger.info(f"  ✗ {chat_id}: нет сообщений владельца")

                # Пауза между чатами (анти-флуд)
                await asyncio.sleep(1.0)

            except Exception as e:
                logger.error(f"Ошибка сканирования {chat_id}: {e}")

        total = sum(len(v) for v in result.values())
        logger.info(
            f"Telethon: стиль-сканирование завершено — "
            f"{len(result)} чатов, {total} сообщений"
        )

        return result

    async def get_dialogs(self, limit: int = 30) -> list[dict]:
        """
        Список диалогов (для выбора чатов при настройке).

        Returns:
            [{"id", "name", "type", "unread_count"}, ...]
        """
        if not self._started:
            return []

        try:
            dialogs = await self._client.get_dialogs(limit=limit)
            result = []

            for d in dialogs:
                dtype = "unknown"
                if d.is_user:
                    dtype = "user"
                elif d.is_group:
                    dtype = "group"
                elif d.is_channel:
                    dtype = "channel"

                result.append({
                    "id": d.entity.id,
                    "name": d.name or "(Без имени)",
                    "type": dtype,
                    "unread_count": d.unread_count,
                    "username": getattr(d.entity, "username", None),
                })

            return result

        except Exception as e:
            logger.error(f"Ошибка получения диалогов: {e}")
            return []

    # ═══════════════════════════════════════════════════════════════════════
    # Авто-ответ в стиле пользователя
    # ═══════════════════════════════════════════════════════════════════════

    async def enable_auto_reply(self, style_guide: str = "") -> None:
        """
        Включить авто-ответ на входящие личные сообщения в стиле пользователя.

        Args:
            style_guide: Описание стиля (если пусто — загружается из StyleAnalyzer).
        """
        if not self._started or not self._client:
            logger.warning("Telethon: невозможно включить авто-ответ — клиент не запущен")
            return

        if self._auto_reply_enabled:
            return  # уже включён

        # Загружаем стиль если не передан
        if style_guide:
            self._style_guide = style_guide
        elif not self._style_guide:
            try:
                from pds_ultimate.core.semantic_engine import style_analyzer
                profile = await style_analyzer.load_existing_profile()
                if profile:
                    self._style_guide = await style_analyzer.get_style_prompt()
            except Exception as e:
                logger.warning(f"Не удалось загрузить профиль стиля: {e}")
                self._style_guide = "Отвечай коротко и по делу, дружелюбно."

        try:
            from telethon import events

            @self._client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
            async def _auto_reply_handler(event):
                if not self._auto_reply_enabled:
                    return
                # Не отвечаем на собственные сообщения и ботов
                try:
                    sender = await event.get_sender()
                    if getattr(sender, "bot", False):
                        return
                    if sender.id == (await self._client.get_me()).id:
                        return
                except Exception:
                    return

                text = event.message.text or ""
                if not text.strip():
                    return

                try:
                    from pds_ultimate.core.llm_engine import llm_engine
                    system = (
                        f"Ты пишешь ответ от лица пользователя. "
                        f"Стиль общения: {self._style_guide}\n"
                        "Отвечай коротко, естественно, в том же тоне что собеседник. "
                        "Не раскрывай что ты ИИ. Пиши только текст ответа."
                    )
                    reply_text = await llm_engine.chat(
                        message=f"Входящее сообщение: «{text}»\nНапиши ответ:",
                        system_prompt=system,
                        task_type="simple_answer",
                    )
                    if reply_text:
                        # Небольшая задержка для естественности
                        await asyncio.sleep(1.5)
                        await event.reply(reply_text)
                        logger.info(
                            f"[AUTO-REPLY] Ответил на сообщение от {getattr(sender, 'first_name', '?')}: "
                            f"{text[:40]}... → {reply_text[:40]}..."
                        )
                except Exception as e:
                    logger.error(f"[AUTO-REPLY] Ошибка генерации ответа: {e}", exc_info=True)

            self._auto_reply_handler = _auto_reply_handler
            self._auto_reply_enabled = True
            logger.info("Telethon авто-ответ включён")

        except Exception as e:
            logger.error(f"Ошибка включения авто-ответа: {e}", exc_info=True)

    async def disable_auto_reply(self) -> None:
        """Выключить авто-ответ."""
        self._auto_reply_enabled = False
        if self._auto_reply_handler and self._client:
            try:
                self._client.remove_event_handler(self._auto_reply_handler)
            except Exception:
                pass
            self._auto_reply_handler = None
        logger.info("Telethon авто-ответ выключен")

    async def update_style(self, style_guide: str) -> None:
        """Обновить стиль авто-ответа без перезапуска."""
        self._style_guide = style_guide
        logger.info("Telethon: стиль авто-ответа обновлён")


# ─── Глобальный экземпляр ────────────────────────────────────────────────────

telethon_client = TelethonClient()
