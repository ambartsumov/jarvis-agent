"""Zero-LLM + optional LLM compression (agentmemory-inspired)."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class CompressedObservation:
    title: str
    narrative: str
    facts: list[str]
    importance: float = 0.5


def compress_zero_llm(role: str, content: str) -> CompressedObservation:
    """Synthetic compression — no tokens spent."""
    text = content.strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    facts: list[str] = []

    for ln in lines[:6]:
        if any(k in ln.lower() for k in ("запомни", "важно", "нужно", "задача", "цель")):
            facts.append(ln[:200])

    # Extract numbers, paths, URLs as facts
    for m in re.findall(r"https?://\S+|/[\w/.-]+|\b\d+[\d.,]*\b", text)[:5]:
        facts.append(m)

    title = f"{role}: {text[:60]}..." if len(text) > 60 else f"{role}: {text}"
    narrative = text[:400] + ("..." if len(text) > 400 else "")
    importance = 0.7 if facts else 0.4
    if role == "assistant" and len(text) > 100:
        importance = 0.5

    return CompressedObservation(title=title, narrative=narrative, facts=facts, importance=importance)
