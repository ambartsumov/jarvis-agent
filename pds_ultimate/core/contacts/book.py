"""Contact directory — names ↔ phone / @nick / email in SQLite."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from sqlalchemy.orm import sessionmaker

from pds_ultimate.config import logger
from pds_ultimate.core.database import Contact, ContactType


class ContactBook:
    def __init__(self) -> None:
        self._session_factory: sessionmaker | None = None

    def set_session_factory(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def _session(self):
        if not self._session_factory:
            raise RuntimeError("ContactBook: session_factory not set")
        return self._session_factory()

    _NAME_RE = re.compile(
        r"[А-ЯA-ZЁ][а-яa-zё]{1,30}(?:\s+[А-ЯA-ZЁ][а-яa-zё]{1,30})?"
    )

    @staticmethod
    def _norm_name(name: str) -> str:
        return re.sub(r"\s+", " ", name.strip())

    @classmethod
    def _clean_name(cls, name: str) -> str:
        n = cls._norm_name(name)
        n = re.sub(r"^(?:запомни|сохрани)\s+(?:что\s+)?", "", n, flags=re.I)
        n = re.sub(r"^(?:что|у|для)\s+", "", n, flags=re.I)
        m = cls._NAME_RE.search(n)
        return m.group(0) if m else n

    @staticmethod
    def _norm_search(value: str) -> str:
        return value.strip().lower()

    @classmethod
    def _name_matches(cls, name: str, query: str) -> bool:
        n = cls._norm_search(name)
        q = cls._norm_search(query)
        if not n or not q:
            return False
        if q in n or n in q:
            return True
        # «Кириллу» / «Кирилла» → «Кирилл»
        if len(q) >= 3 and n.startswith(q[: max(3, len(q) - 1)]):
            return True
        if len(n) >= 3 and q.startswith(n[: max(3, len(n) - 1)]):
            return True
        return False

    @classmethod
    def _contact_matches(cls, c: Contact, query: str) -> bool:
        q = query.strip()
        if not q:
            return True
        ql = cls._norm_search(q)
        fields = [
            c.name,
            c.phone or "",
            c.email or "",
            c.telegram_username or "",
            c.whatsapp_id or "",
            c.notes or "",
        ]
        hay = cls._norm_search(" ".join(fields))
        if ql in hay:
            return True
        if cls._name_matches(c.name, q):
            return True
        if c.telegram_username and ql.lstrip("@") in cls._norm_search(c.telegram_username):
            return True
        return False

    @staticmethod
    def _norm_tg(value: str) -> str:
        v = value.strip()
        if v and not v.startswith("@"):
            v = f"@{v}"
        return v

    def _find_by_name(self, session, name: str) -> Contact | None:
        n = self._clean_name(name)
        if not n:
            return None
        rows = session.query(Contact).filter_by(is_active=True).all()
        for c in rows:
            if self._norm_search(c.name) == self._norm_search(n):
                return c
        for c in rows:
            if self._name_matches(c.name, n):
                return c
        return None

    def save(
        self,
        name: str,
        *,
        phone: str = "",
        email: str = "",
        telegram: str = "",
        whatsapp: str = "",
        notes: str = "",
    ) -> Contact:
        name = self._clean_name(name)
        if not name:
            raise ValueError("Имя контакта обязательно")

        with self._session() as session:
            c = self._find_by_name(session, name)
            if not c:
                c = Contact(name=name, contact_type=ContactType.PERSONAL)
                session.add(c)

            if phone:
                c.phone = phone.strip()
            if email:
                c.email = email.strip().lower()
            if telegram:
                c.telegram_username = self._norm_tg(telegram).lstrip("@")
            if whatsapp:
                c.whatsapp_id = whatsapp.strip()
            if notes:
                old = (c.notes or "").strip()
                c.notes = f"{old}\n{notes}".strip() if old else notes.strip()

            session.commit()
            session.refresh(c)
            logger.info(f"ContactBook: saved «{c.name}» id={c.id}")
            return c

    def find(self, query: str, limit: int = 10) -> list[Contact]:
        q = query.strip()
        with self._session() as session:
            rows = (
                session.query(Contact)
                .filter_by(is_active=True)
                .order_by(Contact.updated_at.desc())
                .all()
            )
            if not q:
                return rows[:limit]
            matched = [c for c in rows if self._contact_matches(c, q)]
            return matched[:limit]

    def resolve_target(self, target: str, *, prefer: str = "") -> tuple[str, Contact | None]:
        """Resolve human name → @nick / phone / whatsapp for messaging tools."""
        t = target.strip()
        if not t:
            return t, None
        if t.startswith("@") or t.startswith("+") or t.lstrip("+").replace(" ", "").isdigit():
            return t, None

        hits = self.find(t, limit=3)
        if not hits:
            return t, None

        c = hits[0]
        if prefer == "whatsapp" and c.whatsapp_id:
            return c.whatsapp_id, c
        if prefer == "email" and c.email:
            return c.email, c
        if c.telegram_username:
            return f"@{c.telegram_username.lstrip('@')}", c
        if c.phone:
            return c.phone, c
        if c.whatsapp_id:
            return c.whatsapp_id, c
        if c.email:
            return c.email, c
        return t, c

    def format_one(self, c: Contact) -> str:
        parts = [f"#{c.id} {c.name}"]
        if c.telegram_username:
            parts.append(f"TG @{c.telegram_username.lstrip('@')}")
        if c.phone:
            parts.append(f"tel {c.phone}")
        if c.email:
            parts.append(f"email {c.email}")
        if c.whatsapp_id:
            parts.append(f"WA {c.whatsapp_id}")
        if c.notes:
            parts.append(f"({c.notes[:80]})")
        return " | ".join(parts)

    def format_context(self, query: str = "", limit: int = 25) -> str:
        try:
            rows = self.find(query, limit=limit)
        except Exception as exc:
            logger.debug(f"ContactBook context: {exc}")
            return ""
        if not rows:
            return ""
        lines = [self.format_one(c) for c in rows]
        return "КОНТАКТЫ (имя → каналы, не спрашивай повторно если есть):\n" + "\n".join(lines)

    def extract_from_text(self, text: str) -> list[dict[str, str]]:
        """Heuristic extraction from owner messages."""
        found: list[dict[str, str]] = []
        t = text.strip()
        if len(t) < 4:
            return found

        name = r"([А-ЯA-ZЁ][а-яa-zё]{1,30})"
        patterns: list[tuple[str, str]] = [
            # «запомни Кирилл это @DurdyP», «@nick — Кирилл»
            (rf"(?:запомни|сохрани)(?:\s+что)?\s+{name}\s+(?:это|—|-|:)\s*(@[\w\d_]{{3,32}})", "tg_name"),
            (rf"(@[\w\d_]{{3,32}})\s*(?:это|—|-|:)\s*{name}", "tg_name_rev"),
            (rf"{name}\s+(?:это|—|-|:)\s*(@[\w\d_]{{3,32}})", "tg_name"),
            (rf"{name}\s+(@[\w\d_]{{3,32}})", "tg_name"),
            # email
            (rf"(?:запомни|сохрани)(?:\s+что)?\s+{name}\s+(?:email|почт\w*|mail)\s*[: ]?\s*([\w.+-]+@[\w.-]+\.\w+)", "email"),
            (rf"{name}(?:а|у|е|ы|и)?\s+(?:email|почт\w*|mail)\s*[: ]?\s*([\w.+-]+@[\w.-]+\.\w+)", "email"),
            # phone
            (rf"(?:запомни|сохрани)(?:\s+что)?\s+{name}\s+(?:номер|телефон|phone|tel)\s*[: ]?\s*(\+?\d[\d\s\-]{{8,18}})", "phone"),
            (rf"{name}(?:а|у|е|ы|и)?\s+(?:номер|телефон|phone|tel)\s*[: ]?\s*(\+?\d[\d\s\-]{{8,18}})", "phone"),
            (rf"(?:номер|телефон)\s+{name}(?:а|у|е|ы|и)?\s*[: ]?\s*(\+?\d[\d\s\-]{{8,18}})", "phone_rev"),
        ]

        seen: set[str] = set()
        for pat, kind in patterns:
            for m in re.finditer(pat, t, re.I):
                if kind == "tg_name":
                    name, tg = self._clean_name(m.group(1)), m.group(2).strip()
                elif kind == "tg_name_rev":
                    tg, name = m.group(1).strip(), self._clean_name(m.group(2))
                elif kind == "email":
                    name, email = self._clean_name(m.group(1)), m.group(2).strip()
                    key = f"{name}|{email}"
                    if key in seen:
                        continue
                    seen.add(key)
                    found.append({"name": name, "email": email})
                    continue
                elif kind == "phone":
                    name, phone = self._clean_name(m.group(1)), re.sub(r"\s+", "", m.group(2))
                    key = f"{name}|{phone}"
                    if key in seen:
                        continue
                    seen.add(key)
                    found.append({"name": name, "phone": phone})
                    continue
                elif kind == "phone_rev":
                    name, phone = self._clean_name(m.group(1)), re.sub(r"\s+", "", m.group(2))
                    key = f"{name}|{phone}"
                    if key in seen:
                        continue
                    seen.add(key)
                    found.append({"name": name, "phone": phone})
                    continue
                else:
                    continue
                if not name:
                    continue
                key = f"{name}|{tg}"
                if key in seen:
                    continue
                seen.add(key)
                found.append({"name": name, "telegram": tg})

        return found

    def auto_save_from_message(self, text: str) -> list[str]:
        saved: list[str] = []
        for item in self.extract_from_text(text):
            try:
                c = self.save(
                    item["name"],
                    phone=item.get("phone", ""),
                    email=item.get("email", ""),
                    telegram=item.get("telegram", ""),
                    whatsapp=item.get("whatsapp", ""),
                )
                saved.append(c.name)
            except Exception as exc:
                logger.debug(f"ContactBook auto_save: {exc}")
        return saved


contact_book = ContactBook()


async def _contact_save(
    name: str,
    phone: str = "",
    email: str = "",
    telegram: str = "",
    whatsapp: str = "",
    notes: str = "",
) -> Any:
    from pds_ultimate.core.tools.base import ToolResult

    try:
        c = await asyncio.to_thread(
            contact_book.save, name,
            phone=phone, email=email, telegram=telegram, whatsapp=whatsapp, notes=notes,
        )
        return ToolResult(success=True, output=f"✅ Контакт сохранён: {contact_book.format_one(c)}")
    except Exception as exc:
        return ToolResult(success=False, output="", error=str(exc))


async def _contact_find(query: str = "", limit: int = 10) -> Any:
    from pds_ultimate.core.tools.base import ToolResult

    try:
        rows = await asyncio.to_thread(contact_book.find, query, limit)
        if not rows:
            return ToolResult(success=True, output="(контактов не найдено)")
        out = "\n".join(contact_book.format_one(c) for c in rows)
        return ToolResult(success=True, output=out)
    except Exception as exc:
        return ToolResult(success=False, output="", error=str(exc))


async def _contact_list(limit: int = 30) -> Any:
    return await _contact_find("", limit=limit)


def register_contact_tools() -> int:
    from pds_ultimate.core.tools.base import ToolSpec
    from pds_ultimate.core.tools.registry import tool_registry

    tools = [
        ToolSpec(
            name="contact_save",
            description=(
                "Сохранить/обновить контакт в базе: имя + телефон, @telegram, email, whatsapp. "
                "Используй когда владелец даёт реквизиты человека — чтобы не спрашивать снова."
            ),
            parameters={"type": "object", "properties": {
                "name": {"type": "string"},
                "phone": {"type": "string"},
                "email": {"type": "string"},
                "telegram": {"type": "string", "description": "@username или username"},
                "whatsapp": {"type": "string"},
                "notes": {"type": "string"},
            }, "required": ["name"]},
            handler=_contact_save, category="contacts", risk="low",
        ),
        ToolSpec(
            name="contact_find",
            description="Найти контакт по имени, @нику, телефону или email в сохранённой базе.",
            parameters={"type": "object", "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            }},
            handler=_contact_find, category="contacts", risk="low",
        ),
        ToolSpec(
            name="contact_list",
            description="Список всех сохранённых контактов.",
            parameters={"type": "object", "properties": {"limit": {"type": "integer"}}},
            handler=_contact_list, category="contacts", risk="low",
        ),
    ]
    for spec in tools:
        tool_registry.register(spec)
    logger.info(f"📇 Registered {len(tools)} contact tools")
    return len(tools)
