"""Built-in agent tools — shell, python, files, web, browser, memory."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import textwrap
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import httpx

from pds_ultimate.config import BASE_DIR, DATA_DIR, USER_FILES_DIR, config, logger
from pds_ultimate.core.memory.hierarchy import hierarchical_memory
from pds_ultimate.core.tools.base import ToolResult, ToolSpec
from pds_ultimate.core.tools.registry import tool_registry

_WORKSPACE = BASE_DIR.parent  # /agent or project root
_BROWSER = None


async def _run_shell(command: str, cwd: str = "", timeout: int = 120) -> ToolResult:
    workdir = Path(cwd).expanduser() if cwd else _WORKSPACE
    if not workdir.exists():
        workdir = _WORKSPACE
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(workdir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        out = stdout.decode(errors="replace")
        err = stderr.decode(errors="replace")
        combined = out
        if err:
            combined += f"\n[stderr]\n{err}"
        success = proc.returncode == 0
        return ToolResult(success=success, output=combined.strip() or "(empty)", error="" if success else err)
    except asyncio.TimeoutError:
        return ToolResult(success=False, output="", error=f"Timeout after {timeout}s")
    except Exception as exc:
        return ToolResult(success=False, output="", error=str(exc))


async def _run_python(code: str) -> ToolResult:
    wrapped = textwrap.dedent(code)
    cmd = ["python3", "-c", wrapped]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(_WORKSPACE),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=90)
        out = stdout.decode(errors="replace")
        err = stderr.decode(errors="replace")
        success = proc.returncode == 0
        return ToolResult(success=success, output=(out or err).strip(), error="" if success else err)
    except Exception as exc:
        return ToolResult(success=False, output="", error=str(exc))


def _safe_path(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = _WORKSPACE / p
    p = p.resolve()
    allowed_roots = {_WORKSPACE.resolve(), USER_FILES_DIR.resolve(), Path.home().resolve()}
    if not any(str(p).startswith(str(root)) for root in allowed_roots):
        raise PermissionError(f"Path outside workspace: {p}")
    return p


async def _read_file(path: str, max_chars: int = 50000) -> ToolResult:
    try:
        p = _safe_path(path)
        text = p.read_text(encoding="utf-8", errors="replace")
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n...[truncated {len(text) - max_chars} chars]"
        return ToolResult(success=True, output=text)
    except Exception as exc:
        return ToolResult(success=False, output="", error=str(exc))


async def _write_file(path: str, content: str) -> ToolResult:
    try:
        p = _safe_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return ToolResult(success=True, output=f"Written {len(content)} chars to {p}")
    except Exception as exc:
        return ToolResult(success=False, output="", error=str(exc))


async def _list_dir(path: str = ".") -> ToolResult:
    try:
        p = _safe_path(path)
        entries = []
        for item in sorted(p.iterdir())[:200]:
            kind = "dir" if item.is_dir() else "file"
            entries.append(f"[{kind}] {item.name}")
        return ToolResult(success=True, output="\n".join(entries) or "(empty)")
    except Exception as exc:
        return ToolResult(success=False, output="", error=str(exc))


async def _web_search(query: str, max_results: int = 5) -> ToolResult:
    try:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 PDS-Agent"})
            html = resp.text
        # Lightweight extraction
        import re

        snippets = re.findall(r'class="result__snippet">(.*?)</', html, re.DOTALL)[:max_results]
        titles = re.findall(r'class="result__a".*?>(.*?)</', html, re.DOTALL)[:max_results]
        lines = []
        for i, title in enumerate(titles):
            clean_title = re.sub(r"<.*?>", "", title).strip()
            snippet = re.sub(r"<.*?>", "", snippets[i]).strip() if i < len(snippets) else ""
            lines.append(f"{i + 1}. {clean_title}\n   {snippet}")
        return ToolResult(success=True, output="\n".join(lines) or "No results")
    except Exception as exc:
        return ToolResult(success=False, output="", error=str(exc))


async def _web_fetch(url: str) -> ToolResult:
    try:
        async with httpx.AsyncClient(timeout=45, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 PDS-Agent"})
            text = resp.text
        import re

        text = re.sub(r"<script.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 12000:
            text = text[:12000] + "..."
        return ToolResult(success=True, output=text or f"HTTP {resp.status_code}, empty body")
    except Exception as exc:
        return ToolResult(success=False, output="", error=str(exc))


async def _browser_action(action: str, url: str = "", selector: str = "", text: str = "") -> ToolResult:
    global _BROWSER
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return ToolResult(success=False, output="", error="playwright not installed")

    from pds_ultimate.config import config

    try:
        if _BROWSER is None:
            pw = await async_playwright().start()
            launch_args = ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
            if config.browser.stealth_enabled:
                launch_args += ["--disable-blink-features=AutomationControlled"]
            # Persistent profile → cookies & logins survive across runs (агент «помнит»).
            profile_dir = DATA_DIR / "browser_profile"
            profile_dir.mkdir(parents=True, exist_ok=True)
            ctx = await pw.chromium.launch_persistent_context(
                str(profile_dir),
                headless=config.browser.headless,
                args=launch_args,
                viewport={"width": config.browser.viewport_width, "height": config.browser.viewport_height},
                locale=config.browser.locale,
                timezone_id=config.browser.timezone,
            )
            # Block heavy assets once at context level (faster page loads).
            async def _block_heavy(route):
                if route.request.resource_type in ("image", "media", "font"):
                    await route.abort()
                else:
                    await route.continue_()
            await ctx.route("**/*", _block_heavy)
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            _BROWSER = {"pw": pw, "browser": ctx, "context": ctx, "page": page}

        page = _BROWSER["page"]

        if action == "goto":
            await page.goto(url, wait_until="commit", timeout=45000)
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=8000)
            except Exception:
                pass
            title = await page.title()
            return ToolResult(success=True, output=f"Opened: {title} ({url})")

        if action == "content":
            content = await page.content()
            import re

            plain = re.sub(r"<[^>]+>", " ", content)
            plain = re.sub(r"\s+", " ", plain).strip()[:12000]
            return ToolResult(success=True, output=plain)

        if action == "click" and selector:
            await page.click(selector, timeout=15000)
            return ToolResult(success=True, output=f"Clicked {selector}")

        if action in ("click_text", "click_label") and text:
            # Click by visible text — much more reliable than desktop OCR for web pages
            loc = page.get_by_text(text, exact=False)
            await loc.first.click(timeout=15000)
            return ToolResult(success=True, output=f"Clicked text «{text}» on page")

        if action == "type" and selector:
            await page.fill(selector, text)
            return ToolResult(success=True, output=f"Typed into {selector}")

        if action == "press":
            key = text or "Enter"
            if selector:
                await page.press(selector, key)
            else:
                await page.keyboard.press(key)
            return ToolResult(success=True, output=f"Pressed {key}")

        if action == "wait":
            ms = int(text) if text and text.isdigit() else 1500
            await page.wait_for_timeout(ms)
            return ToolResult(success=True, output=f"Waited {ms}ms")

        if action in ("solve_captcha", "captcha"):
            from pds_ultimate.integrations.captcha import CaptchaSolver, solve_page_captcha

            solver = CaptchaSolver(config.captcha.api_key)
            if not config.captcha.enabled:
                return ToolResult(success=False, output="", error="CAPTCHA_ENABLED=false")
            if not solver.available:
                return ToolResult(
                    success=False, output="",
                    error="CAPTCHA_API_KEY не задан. Получи ключ на 2captcha.com и добавь в .env",
                )
            msg = await solve_page_captcha(page, solver)
            ok = "решена" in msg.lower() or "token" in msg.lower() or "image" in msg.lower()
            return ToolResult(success=ok, output=msg, error="" if ok else msg)

        if action == "screenshot":
            import time as _t

            path = USER_FILES_DIR / f"screenshot_{int(_t.time())}.png"
            full = (selector or "").lower() in ("full", "fullpage", "page")
            await page.screenshot(path=str(path), full_page=full)
            return ToolResult(
                success=True,
                output=f"Screenshot saved: {path}",
                artifacts=[{"type": "file", "path": str(path)}],
            )

        return ToolResult(success=False, output="", error=f"Unknown browser action: {action}")
    except Exception as exc:
        return ToolResult(success=False, output="", error=str(exc))


async def _str_replace(path: str, old_str: str, new_str: str) -> ToolResult:
    """Precise edit: replace exactly one occurrence of old_str with new_str."""
    try:
        p = _safe_path(path)
        if not p.exists():
            return ToolResult(success=False, output="", error=f"File not found: {p}")
        text = p.read_text(encoding="utf-8", errors="replace")
        count = text.count(old_str)
        if count == 0:
            return ToolResult(success=False, output="", error="old_str not found in file")
        if count > 1:
            return ToolResult(
                success=False, output="",
                error=f"old_str is not unique ({count} matches). Add more context.",
            )
        p.write_text(text.replace(old_str, new_str, 1), encoding="utf-8")
        return ToolResult(success=True, output=f"Edited {p} (1 replacement)")
    except Exception as exc:
        return ToolResult(success=False, output="", error=str(exc))


async def _grep_search(pattern: str, path: str = ".", max_results: int = 50) -> ToolResult:
    """Search file contents for a regex pattern (ripgrep if available, else Python)."""
    try:
        root = _safe_path(path)
    except Exception as exc:
        return ToolResult(success=False, output="", error=str(exc))

    rg = await _run_shell(
        f'rg -n --no-heading -m {max_results} -e {json.dumps(pattern)} .',
        cwd=str(root), timeout=30,
    )
    if rg.success or rg.output:
        out = rg.output if rg.output != "(empty)" else "No matches"
        return ToolResult(success=True, output=out[:8000])

    # Fallback: pure-python recursive scan
    import re as _re
    try:
        rx = _re.compile(pattern)
    except _re.error as exc:
        return ToolResult(success=False, output="", error=f"bad regex: {exc}")
    hits: list[str] = []
    for f in root.rglob("*"):
        if not f.is_file() or f.stat().st_size > 1_000_000:
            continue
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{f}:{i}:{line.strip()[:200]}")
                    if len(hits) >= max_results:
                        break
        except Exception:
            continue
        if len(hits) >= max_results:
            break
    return ToolResult(success=True, output="\n".join(hits) or "No matches")


async def _find_files(pattern: str, path: str = ".", max_results: int = 100) -> ToolResult:
    """Find files by glob pattern."""
    try:
        root = _safe_path(path)
        matches = [str(p) for p in list(root.rglob(pattern))[:max_results]]
        return ToolResult(success=True, output="\n".join(matches) or "No files")
    except Exception as exc:
        return ToolResult(success=False, output="", error=str(exc))


async def _attach_file(path: str, caption: str = "") -> ToolResult:
    """Deliver a file/image straight into the chat (as a Telegram attachment)."""
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return ToolResult(success=False, output="", error=f"Файл не найден: {p}")
        return ToolResult(
            success=True,
            output=f"Файл прикреплён к ответу в чат: {p.name}" + (f" — {caption}" if caption else ""),
            artifacts=[{"type": "file", "path": str(p), "caption": caption}],
        )
    except Exception as exc:
        return ToolResult(success=False, output="", error=str(exc))


async def close_browser() -> None:
    """Cleanly shut down the shared browser to avoid resource leaks on shutdown."""
    global _BROWSER
    if _BROWSER is None:
        return
    try:
        if _BROWSER.get("page"):
            await _BROWSER["page"].close()
        if _BROWSER.get("browser"):
            await _BROWSER["browser"].close()
        if _BROWSER.get("pw"):
            await _BROWSER["pw"].stop()
    except Exception as exc:
        logger.debug(f"Browser cleanup: {exc}")
    finally:
        _BROWSER = None


async def _remember(user_id: int, fact: str, key: str = "") -> ToolResult:
    mid = hierarchical_memory.remember_fact(user_id, fact, key=key)
    return ToolResult(success=True, output=f"Remembered #{mid}: {fact}")


async def _recall(user_id: int, query: str = "") -> ToolResult:
    facts = hierarchical_memory.recall(user_id, query)
    if not facts:
        return ToolResult(success=True, output="No matching memories.")
    lines = [f"- {f['content']}" for f in facts]
    return ToolResult(success=True, output="\n".join(lines))


async def _forget(user_id: int, query: str) -> ToolResult:
    n = hierarchical_memory.forget(user_id, query)
    return ToolResult(success=True, output=f"Забыто записей: {n}")


def register_builtin_tools(user_id: int = 0) -> int:
    """Register all built-in tools. user_id injected at runtime via closure where needed."""

    tools = [
        ToolSpec(
            name="shell_execute",
            description="Execute any shell command on the server. Full system access for the owner.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                    "cwd": {"type": "string", "description": "Working directory (optional)"},
                },
                "required": ["command"],
            },
            handler=_run_shell,
            category="system",
            risk="high",
        ),
        ToolSpec(
            name="python_execute",
            description="Run Python code and return stdout/stderr.",
            parameters={
                "type": "object",
                "properties": {"code": {"type": "string", "description": "Python source code"}},
                "required": ["code"],
            },
            handler=_run_python,
            category="system",
            risk="high",
        ),
        ToolSpec(
            name="read_file",
            description="Read a text file from workspace or user_files.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            handler=_read_file,
            category="files",
        ),
        ToolSpec(
            name="write_file",
            description="Write or overwrite a text file.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            handler=_write_file,
            category="files",
            risk="medium",
        ),
        ToolSpec(
            name="list_dir",
            description="List directory contents.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Directory path"}},
            },
            handler=_list_dir,
            category="files",
        ),
        ToolSpec(
            name="str_replace",
            description="Precisely edit a file: replace exactly ONE unique occurrence of old_str with new_str. Preferred over write_file for edits.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_str": {"type": "string", "description": "Exact text to replace (must be unique)"},
                    "new_str": {"type": "string", "description": "Replacement text"},
                },
                "required": ["path", "old_str", "new_str"],
            },
            handler=_str_replace,
            category="files",
            risk="medium",
        ),
        ToolSpec(
            name="grep_search",
            description="Search file contents by regex pattern across a directory tree.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern"},
                    "path": {"type": "string", "description": "Root directory (default: workspace)"},
                    "max_results": {"type": "integer"},
                },
                "required": ["pattern"],
            },
            handler=_grep_search,
            category="files",
        ),
        ToolSpec(
            name="find_files",
            description="Find files by glob pattern (e.g. '*.py', '**/test_*.py').",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                "required": ["pattern"],
            },
            handler=_find_files,
            category="files",
        ),
        ToolSpec(
            name="web_search",
            description="Search the web for current information.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                "required": ["query"],
            },
            handler=_web_search,
            category="web",
        ),
        ToolSpec(
            name="web_fetch",
            description="Fetch and extract text from a URL.",
            parameters={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
            handler=_web_fetch,
            category="web",
        ),
        ToolSpec(
            name="browser",
            description=(
                "Browser automation (Playwright Chromium). Actions: "
                "goto (открыть url), content (текст страницы), click (CSS selector), "
                "click_text (клик по видимому тексту на странице — надёжнее OCR!), "
                "type (вписать text в selector), press (клавиша), wait, screenshot, "
                "solve_captcha (авто-решение reCAPTCHA/hCaptcha/Turnstile через 2captcha API). "
                "При капче: solve_captcha → click кнопке отправки. "
                "Для веб-кнопок используй click_text, не desktop OCR."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "goto", "content", "click", "click_text", "type",
                            "press", "wait", "screenshot", "solve_captcha",
                        ],
                    },
                    "url": {"type": "string"},
                    "selector": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["action"],
            },
            handler=_browser_action,
            category="web",
        ),
        ToolSpec(
            name="attach_file",
            description=(
                "Отправить файл или изображение ПРЯМО В ЧАТ владельцу (как вложение Telegram). "
                "Используй это, чтобы доставить результат (скриншот, документ, фото) — НЕ просто "
                "сохраняй на диск и не пиши путь, а прикрепляй файл этим инструментом."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Путь к файлу"},
                    "caption": {"type": "string"},
                },
                "required": ["path"],
            },
            handler=_attach_file,
            category="files",
        ),
        ToolSpec(
            name="remember",
            description="Save an important fact to long-term memory.",
            parameters={
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer"},
                    "fact": {"type": "string"},
                    "key": {"type": "string"},
                },
                "required": ["user_id", "fact"],
            },
            handler=_remember,
            category="memory",
        ),
        ToolSpec(
            name="recall",
            description="Search long-term memory for relevant facts.",
            parameters={
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer"},
                    "query": {"type": "string"},
                },
                "required": ["user_id"],
            },
            handler=_recall,
            category="memory",
        ),
        ToolSpec(
            name="forget",
            description="Forget (delete) long-term memories matching a query. Use when the user asks to forget something.",
            parameters={
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer"},
                    "query": {"type": "string"},
                },
                "required": ["user_id", "query"],
            },
            handler=_forget,
            category="memory",
            risk="medium",
        ),
    ]

    for spec in tools:
        tool_registry.register(spec)

    logger.info(f"Registered {len(tools)} built-in tools")
    return len(tools)
