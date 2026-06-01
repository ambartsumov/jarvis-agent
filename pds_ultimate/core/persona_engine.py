"""Per-contact communication style — how the owner writes TO each person."""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pds_ultimate.config import BASE_DIR, config, logger

_STORE = BASE_DIR / "data" / "contact_personas.json"
_MAX_SAMPLES = 40
_OWNER_BOT_KEY = "bot:owner"


@dataclass
class ContactPersona:
    key: str
    display_name: str = ""
    channel: str = ""  # telegram | whatsapp | bot
    samples: list[str] = field(default_factory=list)
    avg_len: float = 0.0
    emoji_rate: float = 0.0
    updated_at: float = 0.0

    def rebuild_stats(self) -> None:
        if not self.samples:
            return
        lens = [len(s) for s in self.samples]
        self.avg_len = sum(lens) / len(lens)
        emoji = sum(1 for s in self.samples if re.search(r"[\U0001F300-\U0001FAFF]", s))
        self.emoji_rate = emoji / len(self.samples)
        self.updated_at = time.time()


class PersonaEngine:
    """
    Stores how the owner communicates WITH each specific contact.
    Never mix styles — each contact gets an isolated profile.
    """

    def __init__(self) -> None:
        self._session_factory = None
        self._profiles: dict[str, ContactPersona] = {}
        self._load()

    def set_session_factory(self, session_factory) -> None:
        self._session_factory = session_factory

    def _load(self) -> None:
        if not _STORE.exists():
            return
        try:
            raw = json.loads(_STORE.read_text(encoding="utf-8"))
            for key, data in raw.items():
                self._profiles[key] = ContactPersona(**data)
        except Exception as exc:
            logger.warning(f"PersonaEngine load failed: {exc}")

    def save(self) -> None:
        _STORE.parent.mkdir(parents=True, exist_ok=True)
        data = {k: asdict(v) for k, v in self._profiles.items()}
        _STORE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _key(channel: str, contact_id: str | int) -> str:
        ch = channel.lower().strip()
        cid = str(contact_id).strip().lstrip("@")
        if ch == "bot":
            return _OWNER_BOT_KEY
        return f"{ch}:{cid}"

    def learn_outbound(
        self,
        channel: str,
        contact_id: str | int,
        text: str,
        display_name: str = "",
    ) -> None:
        """Record how the owner wrote TO this contact (outgoing)."""
        t = (text or "").strip()
        if len(t) < 2:
            return
        key = self._key(channel, contact_id)
        p = self._profiles.get(key) or ContactPersona(key=key, channel=channel)
        if display_name:
            p.display_name = display_name
        if t not in p.samples:
            p.samples.append(t)
        p.samples = p.samples[-_MAX_SAMPLES:]
        p.rebuild_stats()
        self._profiles[key] = p
        self.save()

    def learn_from_message(
        self,
        chat_id: int,
        text: str,
        is_owner: bool = False,
        display_name: str = "",
    ) -> None:
        """Owner ↔ bot chat — separate profile (assistant mode, not contact mimicry)."""
        if not is_owner:
            self.learn_outbound("bot", str(chat_id), text, display_name or str(chat_id))
            return
        self.learn_outbound("bot", "owner", text, display_name or "owner")

    def get_style_guide(self, chat_id: int) -> str:
        """Style when talking TO this user inside the Telegram bot."""
        if chat_id == config.telegram.owner_id:
            return ""
        key = self._key("bot", str(chat_id))
        return self._format_guide(self._profiles.get(key), context="bot_user")

    def get_messaging_style(
        self,
        channel: str,
        contact_ref: str | int,
        display_name: str = "",
    ) -> str:
        """Style when writing AS owner TO a specific contact (TG/WA)."""
        ref = str(contact_ref).strip()
        if ref.startswith("@"):
            ref = ref[1:]
        key = self._key(channel, ref)
        p = self._profiles.get(key)
        if not p and ref.lstrip("-").isdigit():
            p = self._profiles.get(self._key(channel, int(ref)))
        if display_name and p:
            p.display_name = display_name
        return self._format_guide(p, context="messaging", display_name=display_name)

    def _format_guide(
        self,
        p: ContactPersona | None,
        context: str,
        display_name: str = "",
    ) -> str:
        if not p or not p.samples:
            if context == "messaging":
                name = display_name or "собеседник"
                return (
                    f"Пишешь от имени владельца {name}. Пока мало данных о стиле с ним — "
                    "коротко, естественно, как в личке. Не смешивай стиль других контактов."
                )
            return ""

        name = p.display_name or display_name or "контакт"
        samples = p.samples[-8:]
        lines = "\n".join(f"• «{s[:120]}»" for s in samples)
        length_hint = "коротко" if p.avg_len < 35 else ("средне" if p.avg_len < 90 else "развёрнуто")
        emoji_hint = "с эмодзи" if p.emoji_rate > 0.25 else ("редко эмодзи" if p.emoji_rate < 0.08 else "умеренно эмодзи")

        return (
            f"СТИЛЬ ТОЛЬКО ДЛЯ «{name}» ({p.channel or 'контакт'}). "
            f"Никогда не смешивай с другими людьми.\n"
            f"Длина: {length_hint} (~{int(p.avg_len)} симв.), {emoji_hint}.\n"
            f"Примеры как владелец писал именно этому человеку:\n{lines}\n"
            "Копируй манеру, слова и тон из примеров — не канцелярит."
        )

    def get_style_context(self, user_id: int) -> str:
        return self.get_style_guide(user_id)


persona_engine = PersonaEngine()
