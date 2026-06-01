"""Manus-style tool filtering — small schema set = faster LLM + fewer mistakes."""

from __future__ import annotations

import re
from typing import Any

# ── Tiers (union only what the message needs; hard cap at end) ───────────────

# Always-on core (~10) — enough for most tasks like Manus
_TIER_CORE = frozenset({
    "shell_execute", "read_file", "write_file", "list_dir",
    "remember", "recall", "attach_file",
    "web_search", "web_fetch", "desktop", "browser",
})

_TIER_CODE = frozenset({
    "python_execute", "grep_search", "find_files", "str_replace",
})

_TIER_MSG = frozenset({
    "telegram_send", "telegram_read", "telegram_dialogs",
    "whatsapp_send", "whatsapp_read",
    "email_send", "email_read",
    "contact_save", "contact_find", "contact_list", "contact_style_get",
})

_TIER_AUTONOMY = frozenset({
    "directive_add", "directive_list", "directive_remove",
    "schedule_add", "schedule_list", "schedule_today", "schedule_remove",
    "gcal_sync", "gcal_list", "gcal_add", "gcal_clear_day",
})

_TIER_META = frozenset({"create_tool", "plan_and_execute"})

_MAX_TOOLS = 16

_PATTERNS: list[tuple[re.Pattern[str], frozenset[str]]] = [
    (re.compile(r"хром|chrome|chromium|браузер|browser|сайт|http|\.com|капч", re.I), frozenset({"browser"})),
    (re.compile(r"код|python|grep|refactor|\.py\b|script|редактор|edit_text|str_replace", re.I), _TIER_CODE),
    (
        re.compile(
            r"telegram|телеграм|whatsapp|вотс|email|почт|напиши|ответь|отправ|диалог|@\w|сообщ",
            re.I,
        ),
        _TIER_MSG,
    ),
    (
        re.compile(
            r"расписан|календар|directive|напомин|событ|встреч|завтра|послезавтра|gcal|schedule",
            re.I,
        ),
        _TIER_AUTONOMY,
    ),
    (re.compile(r"сложн|несколько шаг|план|research.*build|проект", re.I), _TIER_META),
]


def select_tool_schemas(message: str, all_schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a focused subset of tool schemas (Manus-style, max ~16)."""
    names = {s.get("function", {}).get("name", "") for s in all_schemas}
    chosen: set[str] = set(_TIER_CORE) & names

    for pattern, tier in _PATTERNS:
        if pattern.search(message):
            chosen |= tier & names

    # Compound / long requests — add code + messaging if hinted
    if len(message) > 100 or message.lower().count(" и ") >= 2:
        chosen |= (_TIER_CODE | _TIER_MSG) & names

    # Hard cap: prefer core + matched tiers, drop meta first
    if len(chosen) > _MAX_TOOLS:
        priority = list(_TIER_CORE & chosen)
        rest = [n for n in sorted(chosen - _TIER_CORE) if n not in _TIER_META]
        meta = [n for n in _TIER_META if n in chosen]
        trimmed = set(priority)
        for n in rest:
            if len(trimmed) >= _MAX_TOOLS:
                break
            trimmed.add(n)
        for n in meta:
            if len(trimmed) >= _MAX_TOOLS:
                break
            trimmed.add(n)
        chosen = trimmed

    chosen &= names
    return [s for s in all_schemas if s.get("function", {}).get("name", "") in chosen]


def describe_active_tools(schemas: list[dict[str, Any]]) -> str:
    """One-line catalog injected into the system prompt for this turn."""
    names = sorted(s.get("function", {}).get("name", "") for s in schemas)
    if not names:
        return "ДОСТУПНЫЕ ИНСТРУМЕНТЫ: (нет)"
    grouped: dict[str, list[str]] = {}
    for s in schemas:
        fn = s.get("function", {})
        name = fn.get("name", "")
        cat = (s.get("_category") or fn.get("description", "")[:20] or "general")
        grouped.setdefault(str(cat)[:12], []).append(name)
    # Flat list is clearer for the model
    return "ДОСТУПНЫЕ ИНСТРУМЕНТЫ (" + str(len(names)) + "): " + ", ".join(names)
