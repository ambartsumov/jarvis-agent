"""Self-improvement engine — learn from past runs (errors + winning recipes).

Zero-LLM, fully heuristic. After every agent run we mine the executed steps for:
  • Failure lessons — a tool errored; we store a compact, actionable note so the
    same mistake is avoided next time ("не повторяй провал").
  • Success recipes — a multi-step task finished cleanly; we store the working
    tool sequence so a similar task can be solved faster next time.

Lessons live in the shared MemoryStore under layer="lesson" and are recalled by
BM25 against the current query, then injected into the system prompt.
"""

from __future__ import annotations

import re

from pds_ultimate.config import logger
from pds_ultimate.core.memory.hierarchy import hierarchical_memory
from pds_ultimate.core.memory.store import MemoryStore

_STOP = {
    "и", "в", "во", "на", "с", "со", "по", "для", "что", "как", "это", "мне",
    "мой", "моя", "его", "ее", "их", "там", "тут", "же", "бы", "ли", "не", "ни",
    "от", "до", "за", "из", "о", "об", "а", "но", "или", "у", "к", "то", "так",
    "the", "a", "an", "to", "of", "in", "on", "for", "and", "or", "is", "it",
    "открой", "запусти", "сделай", "пожалуйста", "давай", "нужно", "надо",
}

# Map common error fragments → an actionable fix hint (genuinely useful).
_FIX_HINTS: list[tuple[str, str]] = [
    (r"command not found|not found.*command|no such file", "→ бинарь отсутствует: поставь пакет (apt/snap) или используй другой бинарь/способ"),
    (r"not installed|modulenotfound|no module named", "→ зависимость не установлена: поставь её (pip/apt) перед использованием"),
    (r"permission denied|not permitted|operation not permitted", "→ нет прав: используй sudo (SUDO_PASSWORD) или другой путь"),
    (r"timeout|timed out", "→ долгий ответ: увеличь ожидание или выбери более лёгкий путь"),
    (r"connection refused|connection error|network|getaddrinfo|name resolution", "→ сеть/прокси: проверь подключение, повтори или иди напрямую"),
    (r"selector|no element|element not found|locator|waiting for", "→ селектор не найден: перечитай страницу (content) и используй click_text по видимому тексту"),
    (r"unknown.*action|unknown tool", "→ неверное действие/инструмент: сверься со списком допустимых action"),
    (r"captcha", "→ капча: вызови browser(solve_captcha) до отправки формы"),
    (r"display|wayland|x11|xdotool|ydotool|cannot open display", "→ GUI-ввод капризен на Wayland: сначала пробуй терминал (open_app/run/shell)"),
]


def _signature(query: str) -> str:
    """Compact keyword signature of a task (stable, order-insensitive)."""
    words = re.findall(r"[a-zA-Zа-яёА-ЯЁ0-9]+", query.lower())
    keys = [w for w in words if len(w) > 2 and w not in _STOP]
    return " ".join(sorted(dict.fromkeys(keys))[:6]) or query.lower()[:40]


def _short_err(observation: str) -> str:
    """First meaningful line of an error, trimmed (drop tracebacks)."""
    body = observation
    if body.upper().startswith("ERROR:"):
        body = body[6:]
    first = body.strip().splitlines()[0] if body.strip() else body.strip()
    return first.strip()[:140]


def _fix_hint(err: str) -> str:
    low = err.lower()
    for pat, hint in _FIX_HINTS:
        if re.search(pat, low):
            return hint
    return ""


class LessonBook:
    """Persistent, query-addressable lessons & recipes (zero-LLM)."""

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def recall(self, user_id: int, query: str, limit: int = 5) -> str:
        """Return formatted lessons relevant to the current query (for the prompt)."""
        try:
            rows = self.store.recall(user_id, query, layer="lesson", limit=limit)
        except Exception as exc:
            logger.debug(f"LessonBook recall skipped: {exc}")
            return ""
        if not rows:
            return ""
        seen: set[str] = set()
        lines: list[str] = []
        for r in rows:
            c = r["content"].strip()
            if c and c not in seen:
                seen.add(c)
                lines.append(f"- {c}")
        return "\n".join(lines[:limit])

    def record(self, user_id: int, query: str, steps: list, *, final_ok: bool = True) -> int:
        """Mine executed steps for lessons; persist the useful ones. Returns count stored."""
        if not steps:
            return 0
        sig = _signature(query)
        stored = 0
        tool_seq: list[str] = []
        errored: set[str] = set()

        for s in steps:
            tool = getattr(s, "tool_name", "") or ""
            obs = getattr(s, "observation", "") or ""
            if not tool:
                continue
            if tool not in tool_seq:
                tool_seq.append(tool)
            is_err = obs.strip().upper().startswith("ERROR") or "ERROR:" in obs[:24]
            if is_err:
                err = _short_err(obs)
                # one lesson per (tool, error-fingerprint) to avoid bloat
                fp = f"{tool}|{err[:60]}"
                if fp in errored:
                    continue
                errored.add(fp)
                hint = _fix_hint(err)
                content = f"[УРОК] задачи «{sig}»: {tool} → ОШИБКА: {err}. {hint}".strip()
                try:
                    self.store.remember(
                        user_id, content, layer="lesson",
                        key=f"fail:{sig}:{tool}", importance=0.85,
                    )
                    stored += 1
                except Exception as exc:
                    logger.debug(f"LessonBook store(fail) skipped: {exc}")

        # Winning recipe — only for clean, non-trivial multi-step successes.
        meaningful = [t for t in tool_seq if t not in {"recall", "remember", "attach_file"}]
        if final_ok and not errored and len(meaningful) >= 2:
            recipe = " → ".join(meaningful[:8])
            content = f"[РЕЦЕПТ] для «{sig}» сработало: {recipe}"
            try:
                self.store.remember(
                    user_id, content, layer="lesson",
                    key=f"recipe:{sig}", importance=0.7,
                )
                stored += 1
            except Exception as exc:
                logger.debug(f"LessonBook store(recipe) skipped: {exc}")

        if stored:
            logger.info(f"📚 Уроков сохранено: {stored} (sig='{sig}', ошибок={len(errored)})")
        return stored


lesson_book = LessonBook(hierarchical_memory.store)
