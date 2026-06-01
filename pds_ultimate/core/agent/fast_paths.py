"""Instant execution for common commands — skip LLM round-trips (10-30s saved)."""

from __future__ import annotations

import re
from urllib.parse import quote_plus

from pds_ultimate.core.agent.types import AgentResponse, AgentStep
from pds_ultimate.core.tools.registry import tool_registry

# Requests without concrete text — need LLM to compose content.
_VAGUE_WRITE = re.compile(
    r"^(?:какой[\s-]?нибудь\s+)?текст(?:\s+о\s+том\b.*)?$|"
    r"^что[\s-]нибудь$|^любой\s+текст$|^текст$",
    re.I,
)

_WRITE_PATTERNS = [
    re.compile(
        r"(?:открой\s+)?(?:текстов\w*\s+)?(?:редактор|файл)(?:\s+\S+)*\s+и\s+напиш(?:и|ь)\s+(?:в\s+н(?:е|ё)м\s+)?(.+)",
        re.I,
    ),
    re.compile(
        r"напиш(?:и|ь)\s+(?:в\s+)?(?:текстов\w*\s+)?(?:редактор(?:е)?|файл(?:е)?)\s+(.+)",
        re.I,
    ),
]

async def try_fast_path(message: str, user_id: int) -> AgentResponse | None:
    """Return AgentResponse if handled instantly, else None → full ReAct loop."""
    t = message.lower().strip()
    tools_used: list[str] = []
    artifacts: list[dict] = []
    outputs: list[str] = []

    async def _desk(action: str, target: str = "", **kw) -> tuple[bool, str]:
        params = {"action": action, "target": target, **kw}
        r = await tool_registry.execute("desktop", params)
        tools_used.append("desktop")
        if r.artifacts:
            artifacts.extend(r.artifacts)
        line = r.output if r.success else f"ERROR: {r.error}"
        outputs.append(f"desktop({action}): {line}")
        return r.success, line

    async def _browser(action: str, **kw) -> bool:
        r = await tool_registry.execute("browser", {"action": action, **kw})
        tools_used.append("browser")
        if r.artifacts:
            artifacts.extend(r.artifacts)
        line = r.output if r.success else f"ERROR: {r.error}"
        outputs.append(f"browser({action}): {line}")
        return r.success

    # Календарь — только через LLM (gcal_add/gcal_clear_day), без шаблонов.

    # ── Chrome + Work profile (+ optional search) ─────────────────────────────
    if re.search(r"хром|chrome|chromium", t) and re.search(r"\bwork\b|ворк", t):
        if re.search(r"акк|профил|зайди|войди|зайти", t):
            ok, line = await _desk("chrome_profile", "Work")
            if not ok:
                return None
            if re.search(r"кошек|кошк|cat|кот", t):
                await _browser("goto", url="https://www.google.com/search?q=cute+cats&tbm=isch")
            elif re.search(r"найди|поиск|search", t):
                m = re.search(r"найди\s+(.+?)(?:\s+в\s+хром|$)", t)
                q = (m.group(1) if m else "cats").strip()
                q = re.sub(r"фото\s+", "", q)
                await _browser("goto", url=f"https://www.google.com/search?q={quote_plus(q)}")
            return _resp(outputs, tools_used, artifacts, line.split("\n")[0])

    # ── Open Chrome/Chromium only ─────────────────────────────────────────────
    if re.match(r"^(открой\s+)?(хром|chrome|chromium)\.?!?$", t):
        ok, line = await _desk("open_app", "chromium")
        if not ok:
            return None
        return _resp(outputs, tools_used, artifacts, line.split("\n")[0])

    # ── Open common apps via terminal ─────────────────────────────────────────
    for pat, app in [
        (r"открой.*(telegram|телеграм)", "telegram"),
        (r"открой.*(cursor|курсор|vs code|vscode|вс код)", "cursor"),
        (r"открой.*(firefox|firefox)", "firefox"),
        (r"открой.*(rhythmbox|ритмбокс|музык)", "rhythmbox"),
        (r"открой.*(текстов\w*\s+)?редактор", "gnome-text-editor"),
    ]:
        if re.search(pat, t) and not re.search(r"напиш", t):
            ok, line = await _desk("open_app", app)
            if not ok:
                return None
            return _resp(outputs, tools_used, artifacts, line.split("\n")[0])

    # ── Text editor + write (verified: disk + open editor) ────────────────────
    for pat in _WRITE_PATTERNS:
        m = pat.search(message.strip())
        if not m:
            continue
        content = m.group(1).strip().rstrip(".")
        if not content or _VAGUE_WRITE.match(content.strip()):
            return None  # needs LLM to compose text
        ok, line = await _desk("edit_text", content=content)
        if not ok:
            return None
        return _resp(outputs, tools_used, artifacts, line.split("\n")[0])

    # ── Music (local, not YouTube) ────────────────────────────────────────────
    if re.search(r"включи.*музык|музыку|rhythmbox|ритмбокс", t) and "youtube" not in t and "ютуб" not in t:
        ok, line = await _desk("music")
        if not ok:
            return None
        return _resp(outputs, tools_used, artifacts, line)

    # ── Screenshot ────────────────────────────────────────────────────────────
    if re.search(r"скрин(шот)?|screenshot|сними\s+экран", t) and "браузер" not in t:
        ok, line = await _desk("screenshot")
        if not ok:
            return None
        return _resp(outputs, tools_used, artifacts, line)

    return None


def _resp(outputs: list[str], tools_used: list[str], artifacts: list[dict], answer: str) -> AgentResponse:
    ok = not any("ERROR" in o for o in outputs)
    if not ok and not answer.startswith(("⛔", "✅", "Удалено")):
        answer = "Не удалось выполнить:\n" + "\n".join(outputs)
    return AgentResponse(
        answer=answer,
        steps=[AgentStep(iteration=1, thought="fast_path", action="fast_path", observation="\n".join(outputs))],
        tools_used=list(dict.fromkeys(tools_used)),
        verified=ok,
        total_iterations=1,
        artifacts=artifacts,
    )
