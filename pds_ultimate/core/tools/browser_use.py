"""browser_use integration — powerful browser automation via Playwright + AI.

Adapted from OpenManus app/tool/browser_use_tool.py for pds_ultimate's tool system.
Falls back gracefully when browser_use is not installed.

Install: pip install browser-use playwright && playwright install chromium
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from pds_ultimate.config import config, logger
from pds_ultimate.core.tools.base import ToolResult, ToolSpec
from pds_ultimate.core.tools.registry import tool_registry

# ── lazy imports (browser_use is heavy, optional) ────────────────────────────

_BROWSER_AVAILABLE = False
_browser_instance: Any = None
_context_instance: Any = None
_browser_lock = asyncio.Lock()


def _check_browser_use() -> bool:
    global _BROWSER_AVAILABLE
    try:
        import browser_use  # noqa: F401
        _BROWSER_AVAILABLE = True
        return True
    except ImportError:
        return False


async def _ensure_browser() -> Any:
    """Return browser_use BrowserContext, initializing on first call."""
    global _browser_instance, _context_instance

    async with _browser_lock:
        if _context_instance is not None:
            return _context_instance

        from browser_use import Browser, BrowserConfig
        from browser_use.browser.context import BrowserContextConfig

        headless = getattr(
            getattr(config, "browser_config", None), "headless", False)
        disable_security = getattr(
            getattr(config, "browser_config", None), "disable_security", True)

        _browser_instance = Browser(BrowserConfig(
            headless=headless, disable_security=disable_security))
        _context_instance = await _browser_instance.new_context(BrowserContextConfig())
        return _context_instance


async def _close_browser() -> None:
    global _browser_instance, _context_instance
    async with _browser_lock:
        if _context_instance:
            try:
                await _context_instance.close()
            except Exception:
                pass
            _context_instance = None
        if _browser_instance:
            try:
                await _browser_instance.close()
            except Exception:
                pass
            _browser_instance = None


# ── main handler ──────────────────────────────────────────────────────────────

async def _browser_use_handler(
    action: str,
    url: Optional[str] = None,
    index: Optional[int] = None,
    text: Optional[str] = None,
    scroll_amount: Optional[int] = None,
    tab_id: Optional[int] = None,
    query: Optional[str] = None,
    goal: Optional[str] = None,
    keys: Optional[str] = None,
    seconds: Optional[int] = None,
) -> ToolResult:
    if not _check_browser_use():
        return ToolResult(
            success=False,
            output="",
            error=(
                "browser_use library not installed. "
                "Run: pip install browser-use playwright && playwright install chromium"
            ),
        )

    try:
        ctx = await _ensure_browser()

        if action == "go_to_url":
            if not url:
                return ToolResult(success=False, output="", error="url is required")
            page = await ctx.get_current_page()
            await page.goto(url)
            await page.wait_for_load_state()
            return ToolResult(success=True, output=f"Navigated to {url}")

        elif action == "go_back":
            await ctx.go_back()
            return ToolResult(success=True, output="Navigated back")

        elif action == "web_search":
            if not query:
                return ToolResult(success=False, output="", error="query is required")
            # Navigate to DuckDuckGo search (simple, no JS block)
            search_url = f"https://duckduckgo.com/?q={query.replace(' ', '+')}&ia=web"
            page = await ctx.get_current_page()
            await page.goto(search_url)
            await page.wait_for_load_state()
            return ToolResult(success=True, output=f"Searched for: {query}")

        elif action == "click_element":
            if index is None:
                return ToolResult(success=False, output="", error="index is required")
            element = await ctx.get_dom_element_by_index(index)
            if not element:
                return ToolResult(success=False, output="", error=f"Element {index} not found")
            download_path = await ctx._click_element_node(element)
            out = f"Clicked element {index}"
            if download_path:
                out += f" - Downloaded to {download_path}"
            return ToolResult(success=True, output=out)

        elif action == "input_text":
            if index is None or not text:
                return ToolResult(success=False, output="", error="index and text are required")
            element = await ctx.get_dom_element_by_index(index)
            if not element:
                return ToolResult(success=False, output="", error=f"Element {index} not found")
            await ctx._input_text_element_node(element, text)
            return ToolResult(success=True, output=f"Typed '{text}' into element {index}")

        elif action in ("scroll_down", "scroll_up"):
            direction = 1 if action == "scroll_down" else -1
            amount = scroll_amount if scroll_amount is not None else 600
            await ctx.execute_javascript(f"window.scrollBy(0, {direction * amount});")
            return ToolResult(success=True, output=f"Scrolled {'down' if direction > 0 else 'up'} {amount}px")

        elif action == "scroll_to_text":
            if not text:
                return ToolResult(success=False, output="", error="text is required")
            page = await ctx.get_current_page()
            locator = page.get_by_text(text, exact=False)
            await locator.scroll_into_view_if_needed()
            return ToolResult(success=True, output=f"Scrolled to '{text}'")

        elif action == "send_keys":
            if not keys:
                return ToolResult(success=False, output="", error="keys is required")
            page = await ctx.get_current_page()
            await page.keyboard.press(keys)
            return ToolResult(success=True, output=f"Sent keys: {keys}")

        elif action == "extract_content":
            if not goal:
                return ToolResult(success=False, output="", error="goal is required")
            page = await ctx.get_current_page()
            try:
                import markdownify
                content = markdownify.markdownify(await page.content())
            except ImportError:
                content = await page.inner_text("body")

            max_len = 4000
            # Use pds_ultimate's LLM to extract
            from pds_ultimate.core.llm.client import llm_client
            from pds_ultimate.core.llm.router import TaskKind

            prompt = (
                f"Extract content relevant to this goal from the page:\n"
                f"Goal: {goal}\n\n"
                f"Page content (truncated):\n{content[:max_len]}\n\n"
                "Respond concisely with the extracted information."
            )
            answer = await llm_client.chat(
                [{"role": "user", "content": prompt}],
                kind=TaskKind.REASON,
            )
            return ToolResult(success=True, output=answer)

        elif action == "switch_tab":
            if tab_id is None:
                return ToolResult(success=False, output="", error="tab_id is required")
            await ctx.switch_to_tab(tab_id)
            return ToolResult(success=True, output=f"Switched to tab {tab_id}")

        elif action == "open_tab":
            if not url:
                return ToolResult(success=False, output="", error="url is required")
            await ctx.create_new_tab(url)
            return ToolResult(success=True, output=f"Opened new tab: {url}")

        elif action == "close_tab":
            await ctx.close_current_tab()
            return ToolResult(success=True, output="Closed current tab")

        elif action == "wait":
            secs = seconds if seconds is not None else 2
            await asyncio.sleep(secs)
            return ToolResult(success=True, output=f"Waited {secs}s")

        elif action == "get_state":
            state = await ctx.get_state()
            return ToolResult(success=True, output=str(state)[:2000])

        else:
            return ToolResult(success=False, output="", error=f"Unknown action: {action}")

    except Exception as exc:
        logger.error(f"browser_use action '{action}' error: {exc}")
        return ToolResult(success=False, output="", error=str(exc))


# ── registration ──────────────────────────────────────────────────────────────

_BROWSER_USE_SPEC = ToolSpec(
    name="browser_use",
    description=(
        "Advanced browser automation (browser_use + Playwright). "
        "Navigate URLs, click elements, type text, extract content, run web searches, "
        "manage tabs, scroll, send keys. Much more powerful than basic browser tools. "
        "Actions: go_to_url, go_back, web_search, click_element, input_text, "
        "scroll_down, scroll_up, scroll_to_text, send_keys, extract_content, "
        "switch_tab, open_tab, close_tab, wait, get_state."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "Browser action to perform",
                "enum": [
                    "go_to_url", "go_back", "web_search", "click_element",
                    "input_text", "scroll_down", "scroll_up", "scroll_to_text",
                    "send_keys", "extract_content", "switch_tab", "open_tab",
                    "close_tab", "wait", "get_state",
                ],
            },
            "url": {"type": "string", "description": "URL for go_to_url / open_tab"},
            "index": {"type": "integer", "description": "DOM element index for click/input"},
            "text": {"type": "string", "description": "Text to type or scroll-to"},
            "scroll_amount": {"type": "integer", "description": "Pixels to scroll"},
            "tab_id": {"type": "integer", "description": "Tab ID for switch_tab"},
            "query": {"type": "string", "description": "Search query for web_search"},
            "goal": {"type": "string", "description": "Extraction goal for extract_content"},
            "keys": {"type": "string", "description": "Keys for send_keys (e.g. 'Enter', 'Ctrl+a')"},
            "seconds": {"type": "integer", "description": "Seconds to wait"},
        },
        "required": ["action"],
    },
    handler=_browser_use_handler,
    category="browser",
    risk="medium",
)


def register_browser_use_tool() -> None:
    """Register the browser_use tool in the global registry."""
    tool_registry.register(_BROWSER_USE_SPEC)
    logger.debug("browser_use tool registered")
