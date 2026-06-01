"""Channel tools — live messaging across Telegram (userbot), WhatsApp, Email.

Lets the agent read & send messages and conduct real dialogs on the owner's behalf.
Clients are started lazily and work whenever credentials are present (the legacy
*_ENABLED flags are bypassed — if creds exist, the capability is available).
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any

from pds_ultimate.config import config, logger
from pds_ultimate.core.tools.base import ToolResult, ToolSpec
from pds_ultimate.core.tools.registry import tool_registry

# Dedupe identical sends within 45s (fixes double-send bugs)
_recent_sends: dict[str, float] = {}
_SEND_DEDUPE_SEC = 45.0


def _send_dedupe_key(channel: str, target: str, text: str, file_path: str = "") -> str:
    raw = f"{channel}|{target}|{text}|{file_path}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _is_duplicate_send(key: str) -> bool:
    now = time.time()
    expired = [k for k, t in _recent_sends.items() if now - t >
               _SEND_DEDUPE_SEC]
    for k in expired:
        del _recent_sends[k]
    if key in _recent_sends:
        return True
    _recent_sends[key] = now
    return False


def _resolve_channel_target(target: str, *, prefer: str = "") -> tuple[str, Any | None]:
    """Resolve human name to @nick / phone using contact book."""
    try:
        from pds_ultimate.core.contacts.book import contact_book

        return contact_book.resolve_target(target, prefer=prefer)
    except Exception as exc:
        logger.debug(f"Contact resolve skipped: {exc}")
        return target, None


# ─── Telegram (Telethon userbot) ──────────────────────────────────────────────
async def _ensure_telethon():
    from pds_ultimate.integrations.telethon_client import telethon_client

    if not getattr(telethon_client, "_started", False):
        await telethon_client.start()
    return telethon_client


async def _tg_send(
    target: str, text: str = "", reply_to: int | None = None, file_path: str = "",
) -> ToolResult:
    try:
        if not text.strip() and not file_path:
            return ToolResult(success=False, output="", error="Нужен text или file_path")
        resolved_target, contact = _resolve_channel_target(
            target, prefer="telegram")
        dedupe_key = _send_dedupe_key(
            "telegram", resolved_target, text, file_path)
        if _is_duplicate_send(dedupe_key):
            return ToolResult(success=True, output="(уже отправлено — пропуск дубликата)")

        client = await _ensure_telethon()
        if not getattr(client, "_started", False):
            return ToolResult(success=False, output="", error="Telegram userbot не авторизован (telethon_auth.py)")

        if file_path:
            ok = await client.send_file(resolved_target, file_path, caption=text, reply_to=reply_to)
        else:
            ok = await client.send_message(resolved_target, text, reply_to=reply_to)
        if not ok:
            return ToolResult(success=False, output="", error="Не удалось отправить в Telegram")

        suffix = f" (ответом на #{reply_to})" if reply_to else ""
        kind = "фото/файл" if file_path else "сообщение"
        via = f" ({contact.name} → {resolved_target})" if contact and resolved_target != target else ""
        return ToolResult(success=True, output=f"Отправлено {kind} в Telegram → {resolved_target}{via}{suffix}")
    except Exception as exc:
        return ToolResult(success=False, output="", error=str(exc))


async def _tg_read(chat: str, limit: int = 100) -> ToolResult:
    try:
        chat, _ = _resolve_channel_target(chat, prefer="telegram")
        client = await _ensure_telethon()
        if not getattr(client, "_started", False):
            return ToolResult(
                success=False, output="",
                error="Telegram userbot не запущен/не авторизован.",
            )
        msgs = await client.get_messages(chat, limit=min(max(limit, 1), 1000), offset_days=0)
        if not msgs:
            return ToolResult(success=True, output=f"(нет сообщений или чат «{chat}» не найден)")
        # get_messages отдаёт от новых к старым → разворачиваем в хронологию
        msgs = list(reversed(msgs))
        lines = []
        for m in msgs:
            who = "Я" if m["is_owner"] else m.get("from_name", "?")
            rt = f" ↩#{m['reply_to']}" if m.get("reply_to") else ""
            # Форматируем дату
            date_str = ""
            if m.get("date"):
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(m["date"])
                    date_str = f" [{dt.strftime('%d.%m %H:%M')}]"
                except Exception:
                    date_str = f" [{m['date'][:16]}]"
            lines.append(
                f"[#{m.get('id', '?')}{rt}]{date_str} {who}: {m['text']}")
        out = "\n".join(lines)
        out += "\n\n(ответить на сообщение — telegram_send с reply_to=<его #id>)"
        return ToolResult(success=True, output=out)
    except Exception as exc:
        return ToolResult(success=False, output="", error=str(exc))


async def _tg_dialogs(limit: int = 100) -> ToolResult:
    try:
        client = await _ensure_telethon()
        dialogs = await client.get_dialogs(limit=min(max(limit, 1), 200))
        if not dialogs:
            return ToolResult(success=True, output="(нет диалогов)")
        lines = [
            f"[{d['type']}] {d['name']} (id={d['id']}, @{d.get('username') or '—'})" for d in dialogs]
        return ToolResult(success=True, output="\n".join(lines))
    except Exception as exc:
        return ToolResult(success=False, output="", error=str(exc))


# ─── WhatsApp (Green-API) ─────────────────────────────────────────────────────
async def _ensure_whatsapp():
    from pds_ultimate.integrations.whatsapp import wa_client

    if not getattr(wa_client, "_started", False):
        # Bypass WA_ENABLED — start whenever creds exist
        if config.whatsapp.green_api_instance and config.whatsapp.green_api_token:
            wa_client._instance_id = config.whatsapp.green_api_instance
            wa_client._api_token = config.whatsapp.green_api_token
            inst = config.whatsapp.green_api_instance
            wa_client._base_url = f"https://{inst[:4]}.api.greenapi.com/waInstance{inst}"
            import httpx

            proxy = config.telegram.proxy or None
            kwargs: dict = {"timeout": 30.0}
            if proxy:
                kwargs["proxy"] = proxy
            wa_client._http = httpx.AsyncClient(**kwargs)
            wa_client._started = True
    return wa_client


def _normalize_wa_chat(chat: str) -> str:
    chat = chat.strip()
    if "@" in chat:
        return chat
    digits = chat.lstrip("+").replace(" ", "")
    return f"{digits}@c.us"


async def _wa_send(
    chat: str, text: str, reply_to: str | None = None, file_path: str = "",
) -> ToolResult:
    try:
        if not text.strip() and not file_path:
            return ToolResult(success=False, output="", error="Нужен text или file_path")
        resolved_chat, contact = _resolve_channel_target(
            chat, prefer="whatsapp")
        dedupe_key = _send_dedupe_key(
            "whatsapp", resolved_chat, text, file_path)
        if _is_duplicate_send(dedupe_key):
            return ToolResult(success=True, output="(уже отправлено — пропуск дубликата)")

        client = await _ensure_whatsapp()
        if not getattr(client, "_started", False):
            return ToolResult(success=False, output="", error="WhatsApp не настроен (нет Green-API кред)")
        chat_id = _normalize_wa_chat(resolved_chat)
        if file_path:
            ok = await client.send_file(chat_id, file_path, caption=text, quoted_message_id=reply_to)
        else:
            ok = await client.send_message(chat_id, text, quoted_message_id=reply_to)
        suffix = " (ответом)" if reply_to else ""
        via = f" ({contact.name})" if contact and resolved_chat != chat else ""
        return ToolResult(
            success=ok,
            output=f"Отправлено в WhatsApp → {resolved_chat}{via}{suffix}" if ok else "",
            error="" if ok else "Ошибка отправки WA",
        )
    except Exception as exc:
        return ToolResult(success=False, output="", error=str(exc))


async def _contact_style_get(channel: str, target: str) -> ToolResult:
    from pds_ultimate.core.persona_engine import persona_engine

    guide = persona_engine.get_messaging_style(channel, target)
    return ToolResult(success=True, output=guide or "Стиль для контакта пока не накоплен — пиши естественно.")


async def _wa_read(chat: str, limit: int = 50) -> ToolResult:
    try:
        client = await _ensure_whatsapp()
        if not getattr(client, "_started", False):
            return ToolResult(success=False, output="", error="WhatsApp не настроен")
        msgs = await client.get_recent_messages(_normalize_wa_chat(chat), limit=limit, outgoing_only=False)
        if not msgs:
            return ToolResult(success=True, output="(нет сообщений)")
        lines = []
        for m in msgs:
            who = "Я" if m["is_outgoing"] else "Собеседник"
            ts = m.get("timestamp", 0)
            date_str = ""
            if ts:
                try:
                    from datetime import datetime, timezone
                    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                    date_str = f" [{dt.strftime('%d.%m %H:%M')}]"
                except Exception:
                    pass
            lines.append(f"[#{m.get('id', '?')}]{date_str} {who}: {m['text']}")
        out = "\n".join(lines)
        out += "\n\n(ответить на сообщение — whatsapp_send с reply_to=<его #id>)"
        return ToolResult(success=True, output=out)
    except Exception as exc:
        return ToolResult(success=False, output="", error=str(exc))


# ─── Email (Gmail OAuth API → SMTP fallback) ────────────────────────────────
_gmail_client = None


async def _gmail_ready():
    """Lazy Gmail OAuth client (token already in data/gmail_token.json)."""
    global _gmail_client
    if not config.gmail.enabled:
        return None
    try:
        from pds_ultimate.integrations.gmail import GmailClient

        if _gmail_client is None:
            _gmail_client = GmailClient()
        if not _gmail_client._started:
            await _gmail_client.start()
        return _gmail_client if _gmail_client._accounts else None
    except Exception as exc:
        logger.debug(f"Gmail client not ready: {exc}")
        return None


async def _email_send(to: str, subject: str, body: str) -> ToolResult:
    resolved_to, _ = _resolve_channel_target(to, prefer="email")
    # 1) Gmail OAuth API — основной путь (OAuth уже настроен, SMTP часто ломается)
    client = await _gmail_ready()
    if client:
        try:
            result = await client.send_email(resolved_to, subject, body)
            if result.get("id") or result.get("status") == "sent":
                return ToolResult(
                    success=True,
                    output=f"Email отправлен → {resolved_to} (Gmail API, id={result.get('id', '?')})",
                )
            err = result.get("error", "unknown Gmail error")
            logger.warning(f"Gmail API send failed: {err}")
        except Exception as exc:
            logger.warning(f"Gmail API send exception: {exc}")

    # 2) SMTP fallback
    user = config.smtp.user
    password = config.smtp.password
    if not user or not password:
        return ToolResult(
            success=False, output="",
            error=(
                "Email не отправлен. Gmail OAuth недоступен, SMTP не настроен. "
                "Проверь data/gmail_token.json или SMTP_PASSWORD."
            ),
        )

    def _send_smtp() -> str:
        import smtplib
        from email.mime.text import MIMEText
        from email.utils import formataddr

        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = formataddr((config.smtp.from_name, user))
        msg["To"] = resolved_to
        with smtplib.SMTP(config.smtp.host, config.smtp.port, timeout=30) as server:
            if config.smtp.use_tls:
                server.starttls()
            server.login(user, password)
            server.sendmail(user, [resolved_to], msg.as_string())
        return f"Email отправлен → {resolved_to} (SMTP)"

    try:
        out = await asyncio.to_thread(_send_smtp)
        return ToolResult(success=True, output=out)
    except Exception as exc:
        return ToolResult(
            success=False, output="",
            error=f"Email не отправлен (Gmail API и SMTP): {exc}",
        )


async def _email_read(limit: int = 10, folder: str = "INBOX", unread_only: bool = False) -> ToolResult:
    # 1) Сначала пробуем Gmail OAuth API (надёжнее и быстрее IMAP)
    client = await _gmail_ready()
    if client:
        try:
            emails = await client.get_unread(max_results=limit) if unread_only else await client.get_inbox(max_results=limit)
            if emails:
                lines = []
                for e in emails:
                    lines.append(
                        f"── [{e.get('date', '')[:16]}] От: {e.get('from', '')}\n"
                        f"   Тема: {e.get('subject', '(без темы)')}\n"
                        f"   {e.get('body', e.get('snippet', ''))[:500]}"
                    )
                return ToolResult(success=True, output="\n\n".join(lines))
        except Exception as exc:
            logger.debug(
                f"Gmail OAuth read failed, falling back to IMAP: {exc}")

    # 2) IMAP fallback
    user = config.smtp.user
    password = config.smtp.password
    if not user or not password:
        return ToolResult(success=False, output="", error="Email не настроен (нет Gmail OAuth токена и нет SMTP пароля)")

    def _read() -> str:
        import email
        import imaplib
        from email.header import decode_header

        host = "imap.gmail.com" if "gmail" in config.smtp.host else config.smtp.host.replace(
            "smtp", "imap")
        mail = imaplib.IMAP4_SSL(host)
        mail.login(user, password)
        mail.select(folder)
        criterion = "UNSEEN" if unread_only else "ALL"
        _, data = mail.search(None, criterion)
        ids = data[0].split()[-limit:]
        out_lines: list[str] = []
        for num in reversed(ids):
            _, msg_data = mail.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])

            def _dec(val: str) -> str:
                if not val:
                    return ""
                parts = decode_header(val)
                return "".join(
                    (p.decode(enc or "utf-8", "replace")
                     if isinstance(p, bytes) else p)
                    for p, enc in parts
                )

            subject = _dec(msg.get("Subject", ""))
            frm = _dec(msg.get("From", ""))
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(
                            decode=True).decode("utf-8", "replace")
                        break
            else:
                payload = msg.get_payload(decode=True)
                body = payload.decode("utf-8", "replace") if payload else ""
            out_lines.append(
                f"── От: {frm}\nТема: {subject}\n{body.strip()[:600]}")
        mail.logout()
        return "\n\n".join(out_lines) or "(пусто)"

    try:
        out = await asyncio.to_thread(_read)
        return ToolResult(success=True, output=out)
    except Exception as exc:
        return ToolResult(
            success=False, output="",
            error=f"Email не прочитан (Gmail API и IMAP): {exc}",
        )


async def _email_thread_read(thread_id: str, account: str | None = None) -> ToolResult:
    """Прочитать весь email-тред (цепочка ответов) по thread_id."""
    client = await _gmail_ready()
    if not client:
        return ToolResult(success=False, output="", error="Gmail не подключён")
    try:
        thread = await client.get_thread(thread_id, account=account)
        if not thread:
            return ToolResult(success=True, output="(тред не найден)")
        lines = []
        for e in thread:
            lines.append(
                f"── [{e.get('date', '')[:16]}] {e.get('from', '')}\n"
                f"   {e.get('body', e.get('snippet', ''))[:800]}"
            )
        return ToolResult(success=True, output="\n\n".join(lines))
    except Exception as exc:
        return ToolResult(success=False, output="", error=str(exc))


def register_channel_tools() -> int:
    tools = [
        ToolSpec(
            name="telegram_send",
            description=(
                "Отправить сообщение или фото/файл в Telegram (от лица владельца). "
                "file_path — путь к картинке/файлу. Перед текстом — contact_style_get для стиля с этим человеком."
            ),
            parameters={"type": "object", "properties": {
                "target": {"type": "string", "description": "@username, телефон или chat_id"},
                "text": {"type": "string", "description": "Текст или подпись к файлу"},
                "file_path": {"type": "string", "description": "Путь к фото/файлу (необязательно)"},
                "reply_to": {"type": "integer", "description": "id сообщения для reply (необязательно)"}},
                "required": ["target"]},
            handler=_tg_send, category="channels", risk="high",
        ),
        ToolSpec(
            name="telegram_read",
            description="Прочитать последние сообщения из Telegram-чата. Каждое идёт с #id и пометкой ↩ если это ответ.",
            parameters={"type": "object", "properties": {
                "chat": {"type": "string", "description": "@username, телефон или chat_id"},
                "limit": {"type": "integer"}}, "required": ["chat"]},
            handler=_tg_read, category="channels", risk="medium",
        ),
        ToolSpec(
            name="telegram_dialogs", description="Список последних Telegram-диалогов (имена, id, username).",
            parameters={"type": "object", "properties": {
                "limit": {"type": "integer"}}},
            handler=_tg_dialogs, category="channels", risk="medium",
        ),
        ToolSpec(
            name="whatsapp_send",
            description=(
                "Отправить сообщение или фото/файл в WhatsApp. file_path — картинка/документ. "
                "contact_style_get — стиль общения именно с этим человеком."
            ),
            parameters={"type": "object", "properties": {
                "chat": {"type": "string", "description": "Телефон (79991234567) или chatId@c.us"},
                "text": {"type": "string", "description": "Текст или подпись"},
                "file_path": {"type": "string", "description": "Путь к фото/файлу (необязательно)"},
                "reply_to": {"type": "string", "description": "idMessage для reply (необязательно)"}},
                "required": ["chat"]},
            handler=_wa_send, category="channels", risk="high",
        ),
        ToolSpec(
            name="contact_style_get",
            description=(
                "Получить стиль общения владельца с КОНКРЕТНЫМ контактом (TG/WA). "
                "Используй перед telegram_send/whatsapp_send — стили разных людей не смешивать."
            ),
            parameters={"type": "object", "properties": {
                "channel": {"type": "string", "enum": ["telegram", "whatsapp"]},
                "target": {"type": "string", "description": "@username, chat_id, телефон"},
            }, "required": ["channel", "target"]},
            handler=_contact_style_get, category="channels", risk="low",
        ),
        ToolSpec(
            name="whatsapp_read",
            description="Прочитать историю переписки WhatsApp-чата с датами и именами.",
            parameters={"type": "object", "properties": {
                "chat": {"type": "string", "description": "Телефон (79991234567) или chatId@c.us"},
                "limit": {"type": "integer", "description": "Кол-во сообщений (до 200)"}},
                "required": ["chat"]},
            handler=_wa_read, category="channels", risk="medium",
        ),
        ToolSpec(
            name="email_send",
            description=(
                "Отправить email. Сначала Gmail OAuth API (уже настроен — alexkurumbayev@gmail.com), "
                "затем SMTP. НЕ создавай create_tool для почты — используй этот инструмент."
            ),
            parameters={"type": "object", "properties": {
                "to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}},
                "required": ["to", "subject", "body"]},
            handler=_email_send, category="channels", risk="high",
        ),
        ToolSpec(
            name="email_read",
            description=(
                "Прочитать письма из почтового ящика. "
                "Использует Gmail OAuth API (приоритет), fallback — IMAP. "
                "Возвращает отправителя, тему, дату и тело письма."
            ),
            parameters={"type": "object", "properties": {
                "limit": {"type": "integer", "description": "Кол-во писем (до 50)"},
                "folder": {"type": "string", "description": "Папка (INBOX по умолчанию)"},
                "unread_only": {"type": "boolean", "description": "Только непрочитанные"}}},
            handler=_email_read, category="channels", risk="medium",
        ),
        ToolSpec(
            name="email_thread_read",
            description=(
                "Прочитать всю цепочку писем (тред) по thread_id. "
                "Используй после email_read — берёшь thread_id из результата."
            ),
            parameters={"type": "object", "properties": {
                "thread_id": {"type": "string", "description": "ID треда из email_read"},
                "account": {"type": "string", "description": "work / personal / default (необязательно)"}},
                "required": ["thread_id"]},
            handler=_email_thread_read, category="channels", risk="medium",
        ),
    ]
    for spec in tools:
        tool_registry.register(spec)
    logger.info(f"📡 Registered {len(tools)} channel tools (TG/WhatsApp/Email)")
    return len(tools)
