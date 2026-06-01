"""
PDS-Ultimate Browser Control (Playwright-native)
===================================================
Human-like browser automation через Playwright:
- Открыть/закрыть браузер, вкладки
- Перейти по URL, назад/вперёд
- Кликнуть на элемент по тексту, CSS, XPath, координатам
- Написать текст в поле (как человек — посимвольно)
- Скроллить страницу
- Скриншот страницы
- Извлечь текст, ссылки, элементы
- Заполнить форму
- Нажать кнопку Enter/Tab/Esc
- Дождаться появления элемента
- Выполнить JavaScript
- Работа с несколькими вкладками

Работает как РЕАЛЬНЫЙ пользователь (не headless по умолчанию) —
браузер открывается на экране и всё видно.
"""

from __future__ import annotations

import asyncio
import time

from pds_ultimate.config import USER_FILES_DIR, logger
from pds_ultimate.core.tools.base import ToolResult, ToolSpec
from pds_ultimate.core.tools.registry import tool_registry

# ── Глобальный браузер (один на всё время жизни) ─────────────────────────────
_playwright = None
_browser = None
_pages: list = []          # список открытых страниц
_active_page_idx: int = 0
_lock = asyncio.Lock()


async def _get_playwright():
    global _playwright
    if _playwright is None:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        _playwright = pw
    return _playwright


async def _get_browser():
    global _browser
    if _browser is None or not _browser.is_connected():
        pw = await _get_playwright()
        _browser = await pw.chromium.launch(
            headless=False,
            slow_mo=0,                  # max speed
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--start-maximized",
                "--disable-infobars",
            ],
        )
        logger.info("Browser: Chromium запущен")
    return _browser


async def _get_page() -> tuple[any, bool]:
    """Get active page, open new one if none exist. Returns (page, is_new)."""
    global _pages, _active_page_idx
    browser = await _get_browser()
    # Sync with actual browser pages
    real_pages = browser.contexts[0].pages if browser.contexts else []
    if not real_pages:
        # New context + page
        if not browser.contexts:
            ctx = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
        else:
            ctx = browser.contexts[0]
        page = await ctx.new_page()
        _pages = [page]
        _active_page_idx = 0
        return page, True

    # Use active index
    idx = max(0, min(_active_page_idx, len(real_pages) - 1))
    _active_page_idx = idx
    _pages = list(real_pages)
    return real_pages[idx], False


async def _close_browser():
    global _browser, _playwright, _pages
    if _browser:
        try:
            await _browser.close()
        except Exception:
            pass
        _browser = None
    if _playwright:
        try:
            await _playwright.stop()
        except Exception:
            pass
        _playwright = None
    _pages = []


def _format_element(el: dict) -> str:
    tag = el.get("tag", "")
    text = (el.get("text") or "").strip()[:60]
    placeholder = el.get("placeholder", "")
    idx = el.get("index", "")
    href = el.get("href", "")
    t = f"[{idx}] <{tag}>"
    if text:
        t += f" «{text}»"
    if placeholder:
        t += f" placeholder=«{placeholder}»"
    if href:
        t += f" href={href[:50]}"
    return t


async def _get_interactive_elements(page) -> list[dict]:
    """Get all clickable/interactive elements with indices."""
    try:
        elements = await page.evaluate("""() => {
            const selectors = 'a, button, input, select, textarea, [onclick], [role=button], [role=link], [role=checkbox], [role=menuitem], label';
            const els = Array.from(document.querySelectorAll(selectors));
            return els.slice(0, 120).map((el, i) => ({
                index: i,
                tag: el.tagName.toLowerCase(),
                text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().substring(0, 80),
                placeholder: el.getAttribute('placeholder') || '',
                href: el.href || '',
                type: el.getAttribute('type') || '',
                name: el.getAttribute('name') || '',
                id: el.id || '',
                class: (el.className || '').split(' ').slice(0,3).join(' '),
                rect: (() => { const r = el.getBoundingClientRect(); return {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}; })()
            }));
        }""")
        return elements or []
    except Exception:
        return []


async def _find_element_by_text(page, query: str) -> dict | None:
    """Find best matching interactive element by text/placeholder/id."""
    elements = await _get_interactive_elements(page)
    q = query.lower().strip()
    best, best_score = None, 0
    for el in elements:
        haystack = " ".join([
            el.get("text", ""), el.get("placeholder", ""),
            el.get("name", ""), el.get("id", ""), el.get("class", ""),
        ]).lower()
        score = 0
        if q == haystack.strip():
            score = 100
        elif q in haystack:
            score = 80 - abs(len(haystack) - len(q))
        elif all(word in haystack for word in q.split()):
            score = 60
        if score > best_score:
            best, best_score = el, score
    return best if best_score >= 40 else None


async def _type_human(page, selector_or_text: str, text: str, *, use_index: bool = False) -> tuple[bool, str]:
    """Type text into an element (human-like: click first, then type)."""
    try:
        if use_index:
            idx = int(selector_or_text)
            elements = await _get_interactive_elements(page)
            el = next((e for e in elements if e.get("index") == idx), None)
            if not el:
                return False, f"Элемент #{idx} не найден"
            rect = el.get("rect", {})
            if rect.get("w", 0) > 0:
                x, y = rect["x"] + rect["w"] // 2, rect["y"] + rect["h"] // 2
                await page.mouse.click(x, y)
        else:
            # Try by text match
            el = await _find_element_by_text(page, selector_or_text)
            if el:
                rect = el.get("rect", {})
                if rect.get("w", 0) > 0:
                    x, y = rect["x"] + \
                        rect["w"] // 2, rect["y"] + rect["h"] // 2
                    await page.mouse.click(x, y)
            else:
                # CSS fallback
                await page.click(selector_or_text)

        await asyncio.sleep(0.15)
        # Clear field and type
        await page.keyboard.press("Control+a")
        await page.keyboard.type(text, delay=0)  # delay=0 = max speed
        return True, f"Напечатано в поле: «{text[:100]}»"
    except Exception as e:
        return False, str(e)


# ── Main handler ──────────────────────────────────────────────────────────────

async def _browser_control(
    action: str,
    url: str = "",
    target: str = "",
    text: str = "",
    selector: str = "",
    index: int | None = None,
    x: int | None = None,
    y: int | None = None,
    amount: int = 500,
    keys: str = "",
    js: str = "",
    wait_for: str = "",
    tab: int | None = None,
    timeout: int = 15,
) -> ToolResult:
    """Human-like browser control via Playwright."""

    action = (action or "").lower().strip()

    try:
        async with _lock:
            # ── Управление браузером ──────────────────────────────────────────
            if action in ("close_browser", "quit"):
                await _close_browser()
                return ToolResult(success=True, output="Браузер закрыт")

            if action in ("status", "info"):
                try:
                    page, _ = await _get_page()
                    title = await page.title()
                    url_now = page.url
                    pages_count = len(
                        _browser.contexts[0].pages) if _browser and _browser.contexts else 0
                    return ToolResult(
                        success=True,
                        output=(
                            f"Браузер: открыт\n"
                            f"Вкладок: {pages_count}\n"
                            f"Текущая: «{title}»\n"
                            f"URL: {url_now}"
                        ),
                    )
                except Exception:
                    return ToolResult(success=True, output="Браузер: не запущен")

            # ── Навигация ─────────────────────────────────────────────────────
            if action in ("goto", "open", "navigate", "go_to_url"):
                nav_url = url or target
                if not nav_url:
                    return ToolResult(success=False, output="", error="Укажи url")
                if not nav_url.startswith(("http://", "https://")):
                    nav_url = "https://" + nav_url
                page, _ = await _get_page()
                await page.goto(nav_url, wait_until="domcontentloaded", timeout=timeout * 1000)
                title = await page.title()
                return ToolResult(success=True, output=f"Открыл: «{title}» → {nav_url}")

            if action in ("back", "go_back"):
                page, _ = await _get_page()
                await page.go_back()
                return ToolResult(success=True, output="Назад")

            if action in ("forward", "go_forward"):
                page, _ = await _get_page()
                await page.go_forward()
                return ToolResult(success=True, output="Вперёд")

            if action == "reload":
                page, _ = await _get_page()
                await page.reload()
                return ToolResult(success=True, output="Страница перезагружена")

            # ── Новая вкладка / переключение ──────────────────────────────────
            if action in ("new_tab",):
                global _active_page_idx
                browser = await _get_browser()
                ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
                new_page = await ctx.new_page()
                _pages.append(new_page)
                _active_page_idx = len(_pages) - 1
                if url or target:
                    nav_url = url or target
                    if not nav_url.startswith(("http://", "https://")):
                        nav_url = "https://" + nav_url
                    await new_page.goto(nav_url, wait_until="domcontentloaded", timeout=timeout * 1000)
                    title = await new_page.title()
                    return ToolResult(success=True, output=f"Новая вкладка: «{title}»")
                return ToolResult(success=True, output="Новая вкладка открыта")

            if action in ("switch_tab", "tab"):
                if tab is None and target.isdigit():
                    tab = int(target)
                if tab is None:
                    return ToolResult(success=False, output="", error="Укажи tab=<номер>")
                browser = await _get_browser()
                pages = browser.contexts[0].pages if browser.contexts else []
                if tab < 0 or tab >= len(pages):
                    return ToolResult(success=False, output="", error=f"Вкладка #{tab} не существует (всего {len(pages)})")
                _active_page_idx = tab
                page = pages[tab]
                title = await page.title()
                await page.bring_to_front()
                return ToolResult(success=True, output=f"Вкладка #{tab}: «{title}»")

            if action in ("close_tab",):
                page, _ = await _get_page()
                await page.close()
                _active_page_idx = max(0, _active_page_idx - 1)
                return ToolResult(success=True, output="Вкладка закрыта")

            if action in ("list_tabs",):
                browser = await _get_browser()
                pages = browser.contexts[0].pages if browser.contexts else []
                lines = []
                for i, p in enumerate(pages):
                    try:
                        t = await p.title()
                        u = p.url
                        mark = " ← активная" if i == _active_page_idx else ""
                        lines.append(f"[{i}] «{t}» — {u[:60]}{mark}")
                    except Exception:
                        lines.append(f"[{i}] (закрыта)")
                return ToolResult(success=True, output="\n".join(lines) or "(нет вкладок)")

            # ── Поиск / текущий контент ───────────────────────────────────────
            if action in ("search", "web_search", "google"):
                query = text or target or url
                if not query:
                    return ToolResult(success=False, output="", error="Укажи запрос (text=)")
                search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
                page, _ = await _get_page()
                await page.goto(search_url, wait_until="domcontentloaded", timeout=timeout * 1000)
                # Extract search results
                try:
                    results = await page.evaluate("""() => {
                        const items = document.querySelectorAll('h3');
                        return Array.from(items).slice(0,10).map(h => {
                            const a = h.closest('a');
                            return {title: h.innerText, href: a ? a.href : ''};
                        });
                    }""")
                    lines = [f"{i+1}. {r['title']} — {r['href'][:80]}" for i,
                             r in enumerate(results) if r.get('title')]
                    return ToolResult(success=True, output=f"Google: «{query}»\n\n" + "\n".join(lines[:10]))
                except Exception:
                    return ToolResult(success=True, output=f"Открыл поиск Google: «{query}»")

            if action in ("get_text", "page_text", "read_page"):
                page, _ = await _get_page()
                try:
                    text_content = await page.inner_text("body")
                    title = await page.title()
                    url_now = page.url
                    return ToolResult(
                        success=True,
                        output=(
                            f"«{title}» — {url_now}\n\n"
                            + text_content.strip()[:5000]
                        ),
                    )
                except Exception as e:
                    return ToolResult(success=False, output="", error=str(e))

            if action in ("get_links", "links"):
                page, _ = await _get_page()
                links = await page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('a[href]'))
                        .slice(0, 50)
                        .map(a => ({text: a.innerText.trim().substring(0,60), href: a.href}))
                        .filter(l => l.href && !l.href.startsWith('javascript'));
                }""")
                lines = [
                    f"[{i}] «{l['text']}» → {l['href'][:80]}" for i, l in enumerate(links)]
                return ToolResult(success=True, output="\n".join(lines) or "(нет ссылок)")

            if action in ("get_elements", "list_elements", "elements"):
                page, _ = await _get_page()
                elements = await _get_interactive_elements(page)
                title = await page.title()
                lines = [_format_element(el) for el in elements]
                return ToolResult(
                    success=True,
                    output=(
                        f"Страница: «{title}»\nЭлементы ({len(elements)}):\n"
                        + "\n".join(lines[:80])
                    ),
                )

            if action == "screenshot":
                page, _ = await _get_page()
                path = USER_FILES_DIR / f"browser_{int(time.time())}.png"
                await page.screenshot(path=str(path), full_page=False)
                title = await page.title()
                return ToolResult(
                    success=True,
                    output=f"Скриншот браузера: «{title}»",
                    artifacts=[{"type": "file", "path": str(
                        path), "caption": f"Скриншот: {title}"}],
                )

            if action == "screenshot_full":
                page, _ = await _get_page()
                path = USER_FILES_DIR / f"browser_full_{int(time.time())}.png"
                await page.screenshot(path=str(path), full_page=True)
                return ToolResult(
                    success=True,
                    output="Полный скриншот страницы",
                    artifacts=[{"type": "file", "path": str(
                        path), "caption": "Полная страница"}],
                )

            # ── Клик ─────────────────────────────────────────────────────────
            if action in ("click", "click_element", "click_text", "click_on"):
                page, _ = await _get_page()
                query = target or text or selector

                # По координатам
                if x is not None and y is not None:
                    await page.mouse.click(x, y)
                    await asyncio.sleep(0.2)
                    return ToolResult(success=True, output=f"Клик @ {x},{y}")

                # По индексу
                if index is not None:
                    elements = await _get_interactive_elements(page)
                    el = next(
                        (e for e in elements if e.get("index") == index), None)
                    if not el:
                        return ToolResult(success=False, output="", error=f"Элемент #{index} не найден")
                    rect = el.get("rect", {})
                    cx, cy = rect["x"] + \
                        rect["w"] // 2, rect["y"] + rect["h"] // 2
                    await page.mouse.click(cx, cy)
                    await asyncio.sleep(0.2)
                    return ToolResult(success=True, output=f"Кликнул #{index}: «{el.get('text', '')[:50]}»")

                if not query:
                    return ToolResult(success=False, output="", error="Укажи target, index или x/y")

                # Поиск по тексту
                el = await _find_element_by_text(page, query)
                if el:
                    rect = el.get("rect", {})
                    if rect.get("w", 0) > 0:
                        cx, cy = rect["x"] + \
                            rect["w"] // 2, rect["y"] + rect["h"] // 2
                        await page.mouse.click(cx, cy)
                        await asyncio.sleep(0.25)
                        return ToolResult(success=True, output=f"Кликнул «{el.get('text', '')[:60]}» @ {cx},{cy}")

                # Playwright locator fallback
                try:
                    await page.get_by_text(query, exact=False).first.click(timeout=5000)
                    return ToolResult(success=True, output=f"Кликнул по тексту «{query}»")
                except Exception:
                    pass

                # XPath/CSS fallback
                try:
                    await page.click(query, timeout=5000)
                    return ToolResult(success=True, output=f"Кликнул по селектору «{query}»")
                except Exception as e:
                    return ToolResult(success=False, output="", error=f"Не нашёл «{query}»: {e}")

            # ── Ввод текста ───────────────────────────────────────────────────
            if action in ("type", "input", "fill", "type_text", "write"):
                page, _ = await _get_page()
                input_text = text or target
                if not input_text:
                    return ToolResult(success=False, output="", error="Укажи text=")

                field = selector or target if (selector or target) and (
                    selector or target) != input_text else ""

                # В активный элемент (если нет поля)
                if not field and index is None:
                    await page.keyboard.type(input_text, delay=0)
                    return ToolResult(success=True, output=f"Напечатано: «{input_text[:100]}»")

                # По индексу
                if index is not None:
                    ok, info = await _type_human(page, str(index), input_text, use_index=True)
                    return ToolResult(success=ok, output=info if ok else "", error="" if ok else info)

                # По тексту/placeholder
                ok, info = await _type_human(page, field, input_text)
                return ToolResult(success=ok, output=info if ok else "", error="" if ok else info)

            # ── Скролл ────────────────────────────────────────────────────────
            if action in ("scroll_down", "scroll"):
                page, _ = await _get_page()
                px = amount if amount else 500
                await page.evaluate(f"window.scrollBy(0, {px})")
                return ToolResult(success=True, output=f"Прокрутил вниз на {px}px")

            if action == "scroll_up":
                page, _ = await _get_page()
                px = amount if amount else 500
                await page.evaluate(f"window.scrollBy(0, -{px})")
                return ToolResult(success=True, output=f"Прокрутил вверх на {px}px")

            if action == "scroll_to":
                page, _ = await _get_page()
                query = target or text
                if not query:
                    return ToolResult(success=False, output="", error="Укажи target (текст для прокрутки)")
                try:
                    await page.get_by_text(query, exact=False).first.scroll_into_view_if_needed(timeout=5000)
                    return ToolResult(success=True, output=f"Прокрутил к «{query}»")
                except Exception as e:
                    return ToolResult(success=False, output="", error=str(e))

            if action == "scroll_to_bottom":
                page, _ = await _get_page()
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                return ToolResult(success=True, output="Прокрутил до конца страницы")

            # ── Клавиши ───────────────────────────────────────────────────────
            if action in ("key", "press", "hotkey", "send_keys"):
                page, _ = await _get_page()
                k = keys or target or text
                if not k:
                    return ToolResult(success=False, output="", error="Укажи keys=")
                await page.keyboard.press(k)
                return ToolResult(success=True, output=f"Нажато: {k}")

            if action == "enter":
                page, _ = await _get_page()
                await page.keyboard.press("Enter")
                return ToolResult(success=True, output="Enter нажат")

            if action == "tab":
                page, _ = await _get_page()
                await page.keyboard.press("Tab")
                return ToolResult(success=True, output="Tab нажат")

            if action == "escape":
                page, _ = await _get_page()
                await page.keyboard.press("Escape")
                return ToolResult(success=True, output="Escape нажат")

            if action == "select_all":
                page, _ = await _get_page()
                await page.keyboard.press("Control+a")
                return ToolResult(success=True, output="Выделено всё")

            if action == "copy":
                page, _ = await _get_page()
                await page.keyboard.press("Control+c")
                return ToolResult(success=True, output="Скопировано")

            if action == "paste":
                page, _ = await _get_page()
                await page.keyboard.press("Control+v")
                return ToolResult(success=True, output="Вставлено")

            # ── Ожидание / состояние ──────────────────────────────────────────
            if action == "wait":
                page, _ = await _get_page()
                ms = amount * 1000 if amount <= 30 else amount  # <=30 → секунды, иначе мс
                await asyncio.sleep(min(ms / 1000, 30))
                return ToolResult(success=True, output=f"Подождал {ms}мс")

            if action in ("wait_for", "wait_element"):
                page, _ = await _get_page()
                query = wait_for or target or text
                if not query:
                    return ToolResult(success=False, output="", error="Укажи wait_for=<текст или CSS>")
                try:
                    await page.wait_for_selector(query, timeout=timeout * 1000)
                    return ToolResult(success=True, output=f"Элемент появился: «{query}»")
                except Exception:
                    try:
                        await page.get_by_text(query, exact=False).wait_for(timeout=timeout * 1000)
                        return ToolResult(success=True, output=f"Текст появился: «{query}»")
                    except Exception as e:
                        return ToolResult(success=False, output="", error=f"Ожидание «{query}» провалилось: {e}")

            if action in ("wait_load", "wait_ready"):
                page, _ = await _get_page()
                await page.wait_for_load_state("networkidle", timeout=timeout * 1000)
                title = await page.title()
                return ToolResult(success=True, output=f"Страница загружена: «{title}»")

            # ── JavaScript ────────────────────────────────────────────────────
            if action in ("js", "javascript", "eval"):
                script = js or text or target
                if not script:
                    return ToolResult(success=False, output="", error="Укажи js=")
                page, _ = await _get_page()
                result = await page.evaluate(script)
                return ToolResult(success=True, output=str(result)[:2000])

            # ── Формы ─────────────────────────────────────────────────────────
            if action in ("fill_form", "form"):
                """Fill multiple fields. text = 'field1:value1,field2:value2'"""
                page, _ = await _get_page()
                pairs = text or target
                if not pairs:
                    return ToolResult(success=False, output="", error="Укажи text='поле:значение,поле2:значение2'")
                filled = []
                for pair in pairs.split(","):
                    if ":" not in pair:
                        continue
                    field_name, value = pair.split(":", 1)
                    field_name = field_name.strip()
                    value = value.strip()
                    ok, info = await _type_human(page, field_name, value)
                    if ok:
                        filled.append(f"«{field_name}» = «{value}»")
                    await asyncio.sleep(0.1)
                return ToolResult(
                    success=len(filled) > 0,
                    output="Заполнено: " + "; ".join(filled) if filled else "",
                    error="Не заполнено ни одно поле" if not filled else "",
                )

            # ── Чтение / анализ ───────────────────────────────────────────────
            if action in ("find_text", "find", "search_page"):
                page, _ = await _get_page()
                query = target or text
                if not query:
                    return ToolResult(success=False, output="", error="Укажи target=")
                page_text = await page.inner_text("body")
                q_lower = query.lower()
                found_lines = [
                    line.strip() for line in page_text.splitlines()
                    if q_lower in line.lower() and line.strip()
                ]
                if not found_lines:
                    return ToolResult(success=True, output=f"«{query}» не найден на странице")
                return ToolResult(
                    success=True,
                    output=f"Найдено «{query}»:\n" +
                    "\n".join(found_lines[:20]),
                )

            if action in ("get_url", "current_url"):
                page, _ = await _get_page()
                return ToolResult(success=True, output=page.url)

            if action in ("get_title", "title"):
                page, _ = await _get_page()
                title = await page.title()
                return ToolResult(success=True, output=title)

            # ── Hover ─────────────────────────────────────────────────────────
            if action in ("hover", "mouse_over"):
                page, _ = await _get_page()
                if x is not None and y is not None:
                    await page.mouse.move(x, y)
                    return ToolResult(success=True, output=f"Hover @ {x},{y}")
                query = target or text
                el = await _find_element_by_text(page, query) if query else None
                if el:
                    rect = el.get("rect", {})
                    cx, cy = rect["x"] + \
                        rect["w"] // 2, rect["y"] + rect["h"] // 2
                    await page.mouse.move(cx, cy)
                    return ToolResult(success=True, output=f"Hover над «{query}»")
                return ToolResult(success=False, output="", error="Укажи x/y или target")

            # ── Правый клик ───────────────────────────────────────────────────
            if action in ("right_click",):
                page, _ = await _get_page()
                if x is not None and y is not None:
                    await page.mouse.click(x, y, button="right")
                    return ToolResult(success=True, output=f"Правый клик @ {x},{y}")
                query = target or text
                el = await _find_element_by_text(page, query) if query else None
                if el:
                    rect = el.get("rect", {})
                    cx, cy = rect["x"] + \
                        rect["w"] // 2, rect["y"] + rect["h"] // 2
                    await page.mouse.click(cx, cy, button="right")
                    return ToolResult(success=True, output=f"Правый клик «{query}»")
                return ToolResult(success=False, output="", error="Укажи target или x/y")

            # ── Двойной клик ──────────────────────────────────────────────────
            if action == "double_click":
                page, _ = await _get_page()
                if x is not None and y is not None:
                    await page.mouse.dblclick(x, y)
                    return ToolResult(success=True, output=f"Двойной клик @ {x},{y}")
                query = target or text
                el = await _find_element_by_text(page, query) if query else None
                if el:
                    rect = el.get("rect", {})
                    cx, cy = rect["x"] + \
                        rect["w"] // 2, rect["y"] + rect["h"] // 2
                    await page.mouse.dblclick(cx, cy)
                    return ToolResult(success=True, output=f"Двойной клик «{query}»")
                return ToolResult(success=False, output="", error="Укажи target или x/y")

            # ── Download / Upload ─────────────────────────────────────────────
            if action in ("download", "download_file"):
                page, _ = await _get_page()
                query = target or text
                try:
                    async with page.expect_download(timeout=timeout * 1000) as dload_info:
                        el = await _find_element_by_text(page, query) if query else None
                        if el:
                            rect = el.get("rect", {})
                            await page.mouse.click(rect["x"] + rect["w"] // 2, rect["y"] + rect["h"] // 2)
                        else:
                            await page.click(query, timeout=5000)
                    download = await dload_info.value
                    save_path = str(USER_FILES_DIR /
                                    download.suggested_filename)
                    await download.save_as(save_path)
                    return ToolResult(
                        success=True,
                        output=f"Скачан: {save_path}",
                        artifacts=[
                            {"type": "file", "path": save_path, "caption": "Скачанный файл"}],
                    )
                except Exception as e:
                    return ToolResult(success=False, output="", error=str(e))

            return ToolResult(success=False, output="", error=f"Неизвестное действие браузера: {action}")

    except Exception as exc:
        logger.error(f"browser_control error [{action}]: {exc}", exc_info=True)
        return ToolResult(success=False, output="", error=str(exc))


# ── Регистрация ───────────────────────────────────────────────────────────────

def register_browser_control_tool() -> None:
    tool_registry.register(ToolSpec(
        name="browser",
        description=(
            "Полное управление браузером Chromium как человек (Playwright).\n"
            "НАВИГАЦИЯ: goto «url», back, forward, reload, search «запрос».\n"
            "ВКЛАДКИ: new_tab [url], switch_tab tab=N, list_tabs, close_tab.\n"
            "КЛИК: click target=«текст/кнопка» ИЛИ index=N ИЛИ x=,y= — клик по элементу.\n"
            "ВВОД: type text=«что писать» [index=N или target=«поле»] — написать в поле.\n"
            "  Если поле не указано — пишет в активный элемент (уже кликнутое).\n"
            "СКРОЛЛ: scroll_down/scroll_up [amount=пикс], scroll_to target=«текст», scroll_to_bottom.\n"
            "КЛАВИШИ: key keys=«Enter/Tab/Escape/Control+a/...», enter, tab, escape.\n"
            "ЧТЕНИЕ: get_elements (список кликабельных с индексами), get_text (весь текст),\n"
            "  get_links (все ссылки), find_text target=«слово», get_url, title.\n"
            "СКРИНШОТ: screenshot, screenshot_full.\n"
            "ОЖИДАНИЕ: wait_for target=«текст/CSS», wait_load, wait amount=сек.\n"
            "ФОРМА: fill_form text=«поле:значение,поле2:значение2» — заполнить несколько полей.\n"
            "JS: js js=«код» — выполнить JavaScript.\n"
            "ЗАГРУЗКА: download target=«кнопка» — скачать файл по клику.\n"
            "ПРОЧЕЕ: hover, right_click, double_click, status (что открыто), close_browser.\n\n"
            "WORKFLOW: 1) goto url  2) get_elements  3) click/type/scroll  4) screenshot"
        ),
        parameters={"type": "object", "properties": {
            "action": {"type": "string", "enum": [
                "goto", "open", "navigate", "go_to_url",
                "back", "forward", "reload",
                "search", "web_search", "google",
                "new_tab", "switch_tab", "close_tab", "list_tabs",
                "click", "click_element", "click_text", "click_on",
                "type", "input", "fill", "type_text", "write",
                "fill_form", "form",
                "scroll_down", "scroll", "scroll_up", "scroll_to", "scroll_to_bottom",
                "key", "press", "hotkey", "send_keys",
                "enter", "tab", "escape", "select_all", "copy", "paste",
                "get_elements", "list_elements", "elements",
                "get_text", "page_text", "read_page",
                "get_links", "links",
                "find_text", "find", "search_page",
                "get_url", "current_url",
                "get_title", "title",
                "screenshot", "screenshot_full",
                "wait", "wait_for", "wait_element", "wait_load", "wait_ready",
                "js", "javascript", "eval",
                "hover", "mouse_over",
                "right_click", "double_click",
                "download", "download_file",
                "status", "info",
                "close_browser", "quit",
            ]},
            "url": {"type": "string", "description": "URL для goto/new_tab"},
            "target": {"type": "string", "description": "Текст кнопки/поля для клика/ввода/прокрутки/ожидания"},
            "text": {"type": "string", "description": "Текст для ввода (type) или поиска (find_text)"},
            "selector": {"type": "string", "description": "CSS/XPath селектор (если target не помог)"},
            "index": {"type": "integer", "description": "Индекс элемента из get_elements (0-N)"},
            "x": {"type": "integer", "description": "X-координата для клика/hover"},
            "y": {"type": "integer", "description": "Y-координата для клика/hover"},
            "amount": {"type": "integer", "description": "Пикселей для скролла (default 500) или секунд для wait"},
            "keys": {"type": "string", "description": "Клавиши для key (Enter, Tab, Control+a, Control+c ...)"},
            "js": {"type": "string", "description": "JavaScript код для выполнения"},
            "wait_for": {"type": "string", "description": "CSS/текст для ожидания (wait_for action)"},
            "tab": {"type": "integer", "description": "Номер вкладки (0-based) для switch_tab"},
            "timeout": {"type": "integer", "description": "Таймаут в секундах (default 15)"},
        }, "required": ["action"]},
        handler=_browser_control,
        category="browser",
        risk="high",
    ))
    logger.info("🌐 Browser control tool (Playwright) зарегистрирован")
