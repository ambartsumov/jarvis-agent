"""Pick user-facing final answers — skip internal English planning monologue."""

from __future__ import annotations

import re

_INTERNAL_START = re.compile(
    r"^(Let me|I'll |I will |I'm going to|Checking |Searching |Looking |"
    r"The user |Okay,|OK,|Sure,|First,|Now,|Let me start)",
    re.IGNORECASE,
)


def is_internal_monologue(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    first_line = t.split("\n", 1)[0].strip()
    if _INTERNAL_START.match(first_line):
        return True
    cyrillic = sum(1 for c in t if "\u0400" <= c <= "\u04FF")
    if len(t) > 25 and cyrillic < max(4, int(len(t) * 0.06)):
        return True
    return False


def pick_user_answer(messages) -> str:
    """Last assistant reply suitable for Telegram (Russian user-facing text)."""
    for msg in reversed(messages):
        if getattr(msg, "role", None) != "assistant":
            continue
        content = (getattr(msg, "content", None) or "").strip()
        if not content or is_internal_monologue(content):
            continue
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            continue
        return content
    return ""
