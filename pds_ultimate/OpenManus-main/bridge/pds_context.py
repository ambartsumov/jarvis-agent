"""Optional PDS memory/lessons injection — ONLY context, no tools."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

PDS_ROOT = Path(os.environ.get("PDS_ULTIMATE_DIR", Path(__file__).resolve().parents[2]))


def _ensure_pds_path() -> None:
    parent = str(PDS_ROOT.parent)
    root = str(PDS_ROOT)
    for p in (parent, root):
        if p not in sys.path:
            sys.path.insert(0, p)


def resolve_user_id(context: dict[str, Any], session_id: str = "") -> int:
    """Telegram user id from OpenClaw context (channel id) or explicit user_id."""
    raw = context.get("user_id")
    if raw:
        try:
            uid = int(raw)
            if uid > 0:
                return uid
        except (TypeError, ValueError):
            pass
    for key in ("channel", "channelId", "sender_id", "chat_id"):
        ch = str(context.get(key) or "").strip()
        if ch.isdigit():
            return int(ch)
    try:
        sid = str(session_id or "")
        if sid.isdigit():
            return int(sid)
    except (TypeError, ValueError):
        pass
    fallback = os.environ.get("TG_OWNER_ID") or os.environ.get("PDS_DEFAULT_USER_ID") or "0"
    try:
        return int(fallback)
    except ValueError:
        return 0


_TG_HINT = """[Telegram userbot]
- Любой контакт: telegram_dialogs → telegram_read(chat) → telegram_send(target, text)
- Не bot API — только MCP pds-telegram"""


def build_pds_context(session_id: str, message: str, context: dict[str, Any]) -> str:
    """Memory + lessons only — all tools live in OpenManus."""
    blocks: list[str] = []

    msg_lower = message.lower()
    if any(k in msg_lower for k in ("telegram", "телеграм", "напиши", "сообщени", "диалог", "чат")):
        blocks.append(_TG_HINT)

    injected: list[str] = []
    for key, label in (("memory", "Memory"), ("lessons", "Lessons"), ("style_guide", "Style")):
        text = (context.get(key) or "").strip()
        if text:
            injected.append(f"[{label}]\n{text}")

    if injected:
        blocks.extend(injected)
        return "\n\n".join(blocks)

    try:
        _ensure_pds_path()
        user_id = resolve_user_id(context, session_id)
        if user_id:
            from pds_ultimate.core.memory.hierarchy import hierarchical_memory

            mem = hierarchical_memory.build_context(user_id, query=message)
            if mem:
                blocks.append(f"[Memory]\n{mem}")
            try:
                from pds_ultimate.core.agent.lessons import lesson_book

                lessons = lesson_book.recall(user_id, message)
                if lessons:
                    blocks.append(f"[Lessons]\n{lessons}")
            except Exception:
                pass
    except Exception:
        pass

    return "\n\n".join(blocks) if blocks else ""
