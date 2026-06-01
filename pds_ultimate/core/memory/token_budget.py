"""Token budget manager — inject only what fits."""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Rough estimate: ~4 chars per token for mixed RU/EN."""
    return max(1, len(text) // 4)


def trim_to_budget(items: list[str], budget_tokens: int) -> str:
    parts: list[str] = []
    used = 0
    for item in items:
        cost = estimate_tokens(item)
        if used + cost > budget_tokens:
            break
        parts.append(item)
        used += cost
    return "\n".join(parts)
