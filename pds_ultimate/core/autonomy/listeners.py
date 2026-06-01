"""Incoming-message listeners → TriggerEngine. Real-time, all channels."""

from __future__ import annotations

import asyncio

from pds_ultimate.config import config, logger
from pds_ultimate.core.autonomy.triggers import trigger_engine


async def _start_telegram_listener(owner_id: int) -> bool:
    try:
        from pds_ultimate.integrations.telethon_client import telethon_client

        if telethon_client._incoming_listener_registered:
            logger.debug("TG listener already registered — skip")
            return True

        if not getattr(telethon_client, "_started", False):
            await telethon_client.start()
        client = getattr(telethon_client, "_client", None)
        if not getattr(telethon_client, "_started", False) or client is None:
            return False

        from telethon import events

        @client.on(events.NewMessage(incoming=True))
        async def _on_msg(event):  # noqa: ANN001
            try:
                if event.out or not getattr(event, "is_private", True):
                    return
                sender = await event.get_sender()
                if getattr(sender, "bot", False):
                    return
                fn = getattr(sender, "first_name", "") or ""
                ln = getattr(sender, "last_name", "") or ""
                username = getattr(sender, "username", "") or ""
                name = f"{fn} {ln}".strip() or username or "?"
                text = getattr(event.message, "text", "") or ""
                msg_id = getattr(event.message, "id", None)

                # Голос / видео-кружок → транскрибируем
                if not text and getattr(event.message, "media", None):
                    try:
                        transcript = await telethon_client._transcribe_media(event.message)
                        if transcript:
                            text = f"[голосовое/кружок]: {transcript}"
                    except Exception as exc:
                        logger.debug(f"TG media transcribe: {exc}")

                # Контекст reply — на какое сообщение ответили
                reply_text = ""
                if getattr(event.message, "reply_to_msg_id", None):
                    try:
                        replied = await event.message.get_reply_message()
                        if replied and replied.text:
                            reply_text = replied.text
                    except Exception:
                        pass

                chat_ref = f"@{username}" if username else str(event.chat_id)
                await trigger_engine.handle_incoming(
                    "telegram", name, text, chat_ref, owner_id,
                    msg_id=msg_id, reply_to_text=reply_text,
                )
            except Exception as exc:
                logger.debug(f"TG listener error: {exc}")

        telethon_client._incoming_listener_registered = True
        logger.info("⚡ Trigger listener: Telegram (userbot) online")
        return True
    except Exception as exc:
        logger.warning(f"TG listener skipped: {exc}")
        return False


async def _wa_poll(owner_id: int, interval: float = 4.0) -> None:
    from pds_ultimate.core.tools.channels import _ensure_whatsapp

    client = await _ensure_whatsapp()
    if not getattr(client, "_started", False):
        return
    logger.info("⚡ Trigger listener: WhatsApp polling online")
    http = client._http
    base = client._base_url
    token = client._api_token
    while True:
        try:
            resp = await http.get(f"{base}/receiveNotification/{token}", timeout=35.0)
            data = resp.json()
            if not data:
                await asyncio.sleep(interval)
                continue
            receipt = data.get("receiptId")
            body = data.get("body", {})
            if body.get("typeWebhook") == "incomingMessageReceived":
                md = body.get("messageData", {})
                ext = md.get("extendedTextMessageData", {})
                text = (
                    md.get("textMessageData", {}).get("textMessage", "")
                    or ext.get("text", "")
                )
                msg_id = body.get("idMessage", "")
                reply_text = ext.get("quotedMessage", {}).get("textMessage", "") if ext else ""
                sender_data = body.get("senderData", {})
                sender = sender_data.get("senderName", "") or sender_data.get("sender", "")
                chat_ref = sender_data.get("chatId", "") or sender_data.get("sender", "")
                if text and "@g.us" not in chat_ref and "status@broadcast" not in chat_ref:
                    await trigger_engine.handle_incoming(
                        "whatsapp", sender, text, chat_ref, owner_id,
                        msg_id=msg_id, reply_to_text=reply_text,
                    )
            if receipt:
                await http.delete(f"{base}/deleteNotification/{token}/{receipt}")
        except Exception as exc:
            logger.debug(f"WA poll error: {exc}")
            await asyncio.sleep(interval)


async def start_listeners(owner_id: int | None = None) -> None:
    """Start all incoming-message listeners. Safe to call once at startup."""
    owner_id = owner_id or config.telegram.owner_id
    await _start_telegram_listener(owner_id)
    try:
        from pds_ultimate.core.tools.channels import _ensure_whatsapp

        wa = await _ensure_whatsapp()
        if getattr(wa, "_started", False):
            asyncio.create_task(_wa_poll(owner_id))
    except Exception as exc:
        logger.warning(f"WA listener skipped: {exc}")
