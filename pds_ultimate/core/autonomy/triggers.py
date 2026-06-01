"""TriggerEngine — real-time reactions to incoming messages, driven by directives.

When a message arrives on any channel (Telegram/WhatsApp), the engine finds matching
*trigger directives* (natural-language rules the owner set) and runs the agent to react.
No behavior is hardcoded — the directive text says what to do; the agent executes it
(e.g. auto-reply via telegram_send/whatsapp_send, or notify the owner).
"""

from __future__ import annotations

import hashlib
import re
import time
from collections import deque
from typing import Awaitable, Callable

from pds_ultimate.config import config, logger
from pds_ultimate.core.autonomy.store import Directive, autonomy_store

Notifier = Callable[[int, str], Awaitable[None]]

_GENERIC = {"любое", "любые", "все", "всё", "any", "everything", "всех", "каждое", "каждый"}
_STOP = {"сообщение", "сообщения", "message", "from", "от", "в", "на", "the", "a", "если", "когда", "про", "о"}


def _tokens(s: str) -> list[str]:
    return [w for w in re.findall(r"[\wа-яё@]+", s.lower()) if len(w) >= 3 and w not in _STOP]


def directive_matches(d: Directive, channel: str, sender: str, text: str) -> bool:
    if d.channel and d.channel not in ("", "any", channel):
        return False
    trig = (d.trigger or "").lower().strip()
    if not trig:
        return False
    if any(g in trig for g in _GENERIC):
        return True
    haystack = f"{sender} {text}".lower()
    toks = _tokens(trig)
    if not toks:
        return True  # channel-only trigger
    hay_tokens = _tokens(haystack)
    for raw in toks:
        t = raw.lstrip("@")
        if t in haystack:
            return True
        stem = t[:5]  # crude morphology-tolerant stem (оплату≈оплата)
        for h in hay_tokens:
            if h.startswith(stem) or t.startswith(h[:5]):
                return True
    return False


class TriggerEngine:
    def __init__(self, max_per_minute: int = 12) -> None:
        self._notifier: Notifier | None = None
        self._seen: deque[str] = deque(maxlen=500)
        self._recent_actions: deque[float] = deque(maxlen=100)
        self.max_per_minute = max_per_minute

    def set_notifier(self, notifier: Notifier) -> None:
        self._notifier = notifier

    async def _notify(self, owner_id: int, text: str) -> None:
        if self._notifier:
            try:
                await self._notifier(owner_id, text)
            except Exception as exc:
                logger.debug(f"Trigger notify failed: {exc}")

    def _dedupe(self, channel: str, chat_ref: str, text: str) -> bool:
        key = hashlib.sha1(f"{channel}|{chat_ref}|{text}".encode()).hexdigest()
        if key in self._seen:
            return True
        self._seen.append(key)
        return False

    def _rate_ok(self) -> bool:
        now = time.time()
        while self._recent_actions and now - self._recent_actions[0] > 60:
            self._recent_actions.popleft()
        if len(self._recent_actions) >= self.max_per_minute:
            return False
        self._recent_actions.append(now)
        return True

    async def handle_incoming(
        self, channel: str, sender: str, text: str, chat_ref: str,
        owner_id: int | None = None, *, msg_id: object = None, reply_to_text: str = "",
    ) -> None:
        if not text:
            return
        owner_id = owner_id or config.telegram.owner_id
        if self._dedupe(channel, chat_ref, text):
            return

        directives = autonomy_store.trigger_directives(owner_id, channel)
        matched = [d for d in directives if directive_matches(d, channel, sender, text)]

        # Календарь-осведомлённый автоответ: даже без явной директивы, если владелец
        # сейчас занят (по календарю/расписанию) — агент вежливо отвечает сам.
        from pds_ultimate.core.autonomy.presence import current_activity

        busy = await current_activity(owner_id)

        if not matched and not busy:
            return
        if not self._rate_ok():
            logger.warning("TriggerEngine: rate limit hit, skipping reaction")
            return

        from pds_ultimate.core.agent.ethan import agent

        send_tool = "telegram_send" if channel == "telegram" else "whatsapp_send"
        from pds_ultimate.core.persona_engine import persona_engine

        contact_style = persona_engine.get_messaging_style(channel, chat_ref, sender)
        reply_hint = (
            f"\nЭто сообщение — ответ на твоё: «{reply_to_text[:200]}»." if reply_to_text else ""
        )
        reply_to_hint = (
            f"\nЧтобы ответить ИМЕННО на это сообщение (reply-цитата, как делают люди), "
            f"вызови {send_tool} с reply_to={msg_id!r}." if msg_id else ""
        )

        directive_block = ""
        if matched:
            d = matched[0]
            directive_block = f"\nСработала твоя директива #{d.id}: {d.text}"

        busy_block = ""
        if busy:
            busy_block = (
                f"\n\n[СТАТУС ВЛАДЕЛЬЦА: сейчас ЗАНЯТ — «{busy['title']}» ({busy['range']})]\n"
                f"Владелец Slavik сейчас недоступен. Ответь собеседнику ВЕЖЛИВО и ПО-ЧЕЛОВЕЧЕСКИ "
                f"от первого лица как его ассистент: представься (ты — Итан, AI-ассистент Славика), "
                f"скажи что Славик сейчас занят ({busy['title']}) и ответит позже. Не выдумывай детали. "
                f"Отправь это собеседнику через {send_tool} (ответом на его сообщение), "
                f"а затем сообщи владельцу что ты ответил вместо него."
            )

        task = (
            f"[ВХОДЯЩЕЕ СООБЩЕНИЕ | канал={channel} | от={sender} | chat_ref={chat_ref}"
            f"{f' | msg_id={msg_id}' if msg_id else ''}]\n"
            f"Текст: {text}{reply_hint}{reply_to_hint}"
            f"{directive_block}{busy_block}\n\n"
            f"Адресат для ответа: {chat_ref}. Общайся живо, по-человечески, как в мессенджере — "
            f"коротко и естественно, без канцелярита и без признаков «я бот». "
            f"Действуй сам, затем кратко отчитайся владельцу о том, что сделал.\n\n"
            f"{contact_style}\n"
            f"Перед отправкой через {send_tool} — contact_style_get если нужно уточнить стиль."
        )
        try:
            result = await agent.run(owner_id, task, style_guide=contact_style)
            answer = (result.answer or "").strip()
            if answer:
                await self._notify(owner_id, f"⚡ [{channel}] реакция на «{text[:40]}»:\n{answer}")
        except Exception as exc:
            logger.warning(f"TriggerEngine run failed: {exc}")


trigger_engine = TriggerEngine()
