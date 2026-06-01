"""
PDS-Ultimate Web Tools
=======================
Инструменты для работы с вебом: поиск, браузер, исследования.

ФУНКЦИИ:
- Поиск в интернете
- Просмотр страниц
- Скриншоты сайтов
- Глубокие исследования
- Саммари URL
- Перевод

ARCHITECTURE:
- Playwright для браузера (stealth mode)
- httpx для лёгких запросов
- Anti-detection headers
- VPN proxy support
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from pds_ultimate.config import config, logger
from pds_ultimate.core.tools import Tool, ToolParameter, ToolResult, ToolRegistry

# ─── Web Tools ──────────────────────────────────────────────────────────────


async def tool_web_search(
    query: str,
    num_results: int = 5,
) -> ToolResult:
    """
    Поиск в интернете.
    
    Использует DuckDuckGo/Google API или fallback на httpx.
    """
    try:
        import httpx
        
        # DuckDuckGo HTML search (no API key needed)
        url = "https://html.duckduckgo.com/html/"
        params = {"q": query}
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
        }
        
        proxy = config.deepseek.proxy or config.browser.proxy_server or None
        
        async with httpx.AsyncClient(proxy=proxy, headers=headers) as client:
            response = await client.post(url, data=params, timeout=30)
            response.raise_for_status()
            html = response.text
        
        # Parse results (simplified)
        from bs4 import BeautifulSoup
        
        soup = BeautifulSoup(html, "html.parser")
        results = []
        
        for result in soup.select(".result")[:num_results]:
            title_elem = result.select_one(".result__title")
            snippet_elem = result.select_one(".result__snippet")
            url_elem = result.select_one(".result__url")
            
            if title_elem and snippet_elem:
                results.append({
                    "title": title_elem.get_text(strip=True),
                    "snippet": snippet_elem.get_text(strip=True),
                    "url": url_elem.get("href") if url_elem else "",
                })
        
        if not results:
            return ToolResult(
                "web_search",
                False,
                "Ничего не найдено",
                error="No results",
            )
        
        formatted = f"🔍 Поиск: {query}\n\n"
        for i, r in enumerate(results, 1):
            formatted += f"{i}. {r['title']}\n   {r['snippet'][:150]}\n   {r['url']}\n\n"
        
        return ToolResult(
            "web_search",
            True,
            formatted,
            data={"results": results, "query": query},
        )
        
    except ImportError:
        # Fallback: simple message
        return ToolResult(
            "web_search",
            True,
            f"🔍 Поиск по запросу: {query}\n(требуется BeautifulSoup: pip install beautifulsoup4)",
            data={"query": query},
        )
    except Exception as e:
        logger.error(f"tool_web_search failed: {e}")
        return ToolResult("web_search", False, "", error=str(e))


async def tool_browse_page(
    url: str,
    extract_links: bool = False,
) -> ToolResult:
    """
    Просмотр веб-страницы.
    
    Извлекает заголовок, основной текст, ссылки.
    """
    try:
        import httpx
        from bs4 import BeautifulSoup
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
        }
        
        proxy = config.deepseek.proxy or config.browser.proxy_server or None
        
        async with httpx.AsyncClient(proxy=proxy, headers=headers) as client:
            response = await client.get(url, timeout=30, follow_redirects=True)
            response.raise_for_status()
            html = response.text
        
        soup = BeautifulSoup(html, "html.parser")
        
        # Extract title
        title = soup.title.string if soup.title else "No title"
        
        # Extract main text (simplified)
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        
        text = soup.get_text(separator="\n", strip=True)
        text = text[:3000]  # Limit length
        
        result = f"📄 {title}\n\n{text}"
        
        if extract_links:
            links = [a.get("href") for a in soup.find_all("a", href=True)[:20]]
            result += f"\n\n🔗 Ссылки:\n" + "\n".join(f"• {l}" for l in links)
        
        return ToolResult(
            "browse_page",
            True,
            result,
            data={"title": title, "url": url, "text_length": len(text)},
        )
        
    except Exception as e:
        logger.error(f"tool_browse_page failed: {e}")
        return ToolResult("browse_page", False, "", error=str(e))


async def tool_screenshot(
    url: str,
    full_page: bool = False,
) -> ToolResult:
    """
    Скриншот веб-страницы.
    
    Использует Playwright для рендеринга.
    """
    try:
        from playwright.async_api import async_playwright
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=config.browser.headless,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            
            page = await browser.new_page(
                viewport={"width": config.browser.viewport_width, "height": config.browser.viewport_height}
            )
            
            await page.goto(url, wait_until="networkidle", timeout=30000)
            
            screenshot = await page.screenshot(
                full_page=full_page,
                type="png",
            )
            
            # Save screenshot
            import os
            from datetime import datetime
            
            os.makedirs(config.browser.screenshots_dir, exist_ok=True)
            filename = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            filepath = config.browser.screenshots_dir / filename
            
            with open(filepath, "wb") as f:
                f.write(screenshot)
            
            await browser.close()
            
            return ToolResult(
                "screenshot",
                True,
                f"✅ Скриншот сохранён: {filepath}",
                data={"filepath": str(filepath), "url": url},
            )
            
    except ImportError:
        return ToolResult(
            "screenshot",
            False,
            "Playwright не установлен (playwright install chromium)",
            error="Playwright not installed",
        )
    except Exception as e:
        logger.error(f"tool_screenshot failed: {e}")
        return ToolResult("screenshot", False, "", error=str(e))


async def tool_deep_research(
    topic: str,
    max_pages: int = 5,
) -> ToolResult:
    """
    Глубокое исследование темы.
    
    1. Поиск в интернете
    2. Чтение топ-N страниц
    3. Синтез информации
    """
    try:
        from pds_ultimate.core.llm_engine import llm_engine
        
        # Step 1: Search
        search_result = await tool_web_search(topic, num_results=max_pages)
        
        if not search_result.success or not search_result.data:
            return ToolResult(
                "deep_research",
                False,
                "Не удалось найти информацию",
            )
        
        results = search_result.data.get("results", [])
        
        # Step 2: Read pages
        page_contents = []
        for r in results[:max_pages]:
            if r.get("url"):
                try:
                    page_result = await tool_browse_page(r["url"])
                    if page_result.success:
                        page_contents.append(page_result.data.get("text", "")[:1000])
                except Exception:
                    pass
        
        # Step 3: Synthesize with LLM
        context = "\n\n".join(page_contents)
        
        summary = await llm_engine.summarize(context[:8000])
        
        report = f"""
📚 ИССЛЕДОВАНИЕ: {topic}
═══════════════════════════════

{summary}

Источники:
{chr(10).join(f'• {r.get("title", "Unknown")}' for r in results[:5])}
"""
        
        return ToolResult(
            "deep_research",
            True,
            report,
            data={"summary": summary, "sources": results[:5]},
        )
        
    except Exception as e:
        logger.error(f"tool_deep_research failed: {e}")
        return ToolResult("deep_research", False, "", error=str(e))


async def tool_summarize_url(
    url: str,
) -> ToolResult:
    """
    Краткое саммари веб-страницы.
    """
    try:
        from pds_ultimate.core.llm_engine import llm_engine
        
        # Get page content
        page_result = await tool_browse_page(url)
        
        if not page_result.success:
            return ToolResult(
                "summarize_url",
                False,
                "Не удалось загрузить страницу",
            )
        
        text = page_result.data.get("text", "")
        
        # Summarize
        summary = await llm_engine.summarize(text[:4000])
        
        return ToolResult(
            "summarize_url",
            True,
            f"📄 {url}\n\n{summary}",
            data={"summary": summary, "url": url},
        )
        
    except Exception as e:
        logger.error(f"tool_summarize_url failed: {e}")
        return ToolResult("summarize_url", False, "", error=str(e))


async def tool_translate(
    text: str,
    target_lang: str = "ru",
    source_lang: Optional[str] = None,
) -> ToolResult:
    """
    Перевод текста.
    
    Использует LLM для перевода.
    """
    try:
        from pds_ultimate.core.llm_engine import llm_engine
        
        translation = await llm_engine.translate(text, target_lang, source_lang)
        
        source_info = f"с {source_lang} " if source_lang else ""
        
        return ToolResult(
            "translate",
            True,
            f"🌐 Перевод {source_info}на {target_lang}:\n\n{translation}",
            data={"translation": translation, "target_lang": target_lang},
        )
        
    except Exception as e:
        logger.error(f"tool_translate failed: {e}")
        return ToolResult("translate", False, "", error=str(e))


# ─── Tool Registration ───────────────────────────────────────────────────────

def register_web_tools(registry: ToolRegistry) -> None:
    """Зарегистрировать web инструменты."""
    
    registry.register(
        Tool(
            name="web_search",
            description="Поиск в интернете (DuckDuckGo)",
            parameters=[
                ToolParameter("query", "string", "Поисковый запрос"),
                ToolParameter("num_results", "number", "Количество результатов", default=5, required=False),
            ],
            handler=tool_web_search,
            category="web",
        )
    )
    
    registry.register(
        Tool(
            name="browse_page",
            description="Просмотр веб-страницы (извлечь текст)",
            parameters=[
                ToolParameter("url", "string", "URL страницы"),
                ToolParameter("extract_links", "boolean", "Извлечь ссылки", default=False, required=False),
            ],
            handler=tool_browse_page,
            category="web",
        )
    )
    
    registry.register(
        Tool(
            name="screenshot",
            description="Скриншот веб-страницы",
            parameters=[
                ToolParameter("url", "string", "URL страницы"),
                ToolParameter("full_page", "boolean", "Вся страница или видимая часть", default=False, required=False),
            ],
            handler=tool_screenshot,
            category="web",
        )
    )
    
    registry.register(
        Tool(
            name="deep_research",
            description="Глубокое исследование темы (поиск + чтение + синтез)",
            parameters=[
                ToolParameter("topic", "string", "Тема исследования"),
                ToolParameter("max_pages", "number", "Максимум страниц для чтения", default=5, required=False),
            ],
            handler=tool_deep_research,
            category="web",
        )
    )
    
    registry.register(
        Tool(
            name="summarize_url",
            description="Краткое саммари веб-страницы",
            parameters=[
                ToolParameter("url", "string", "URL страницы"),
            ],
            handler=tool_summarize_url,
            category="web",
        )
    )
    
    registry.register(
        Tool(
            name="translate",
            description="Перевод текста",
            parameters=[
                ToolParameter("text", "string", "Текст для перевода"),
                ToolParameter("target_lang", "string", "Целевой язык (ru/en/etc)", default="ru"),
                ToolParameter("source_lang", "string", "Исходный язык", required=False),
            ],
            handler=tool_translate,
            category="web",
        )
    )


__all__ = [
    "tool_web_search",
    "tool_browse_page",
    "tool_screenshot",
    "tool_deep_research",
    "tool_summarize_url",
    "tool_translate",
    "register_web_tools",
]
