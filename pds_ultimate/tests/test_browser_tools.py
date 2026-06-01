"""
PDS-Ultimate Browser Tools Tests
==================================
Тесты для browser tools (web_search, open_page, screenshot, click, fill).
Все тесты мокают browser_engine чтобы не зависеть от реального Playwright.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pds_ultimate.core.browser_engine import (
    ExtractedData,
    PageInfo,
    PageStatus,
    SearchResult,
)
from pds_ultimate.core.tools import ToolResult

# Патчим глобальный объект в модуле-источнике
_PATCH_TARGET = "pds_ultimate.core.browser_engine.browser_engine"


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def sample_search_results():
    """Примеры результатов поиска."""
    return [
        SearchResult(
            title="Python Tutorial",
            url="https://python.org/tutorial",
            snippet="Learn Python programming",
            position=1,
        ),
        SearchResult(
            title="Python Documentation",
            url="https://docs.python.org",
            snippet="Official Python docs",
            position=2,
        ),
        SearchResult(
            title="Real Python",
            url="https://realpython.com",
            snippet="Python tutorials and articles",
            position=3,
        ),
    ]


@pytest.fixture
def sample_extracted_data():
    """Пример извлечённых данных страницы."""
    return ExtractedData(
        url="https://example.com",
        title="Example Domain",
        text="This domain is for use in illustrative examples. "
             "More information at IANA.",
        links=[
            {"text": "More information...", "href": "https://iana.org"},
        ],
        headings=["Example Domain"],
        images=[],
        tables=[
            [["Header1", "Header2"], ["val1", "val2"]],
        ],
        meta={"description": "Example Domain"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL_WEB_SEARCH
# ═══════════════════════════════════════════════════════════════════════════════


class TestToolWebSearch:
    """Тесты для tool_web_search."""

    @pytest.mark.asyncio
    async def test_web_search_success(self, sample_search_results):
        """Успешный поиск возвращает результаты."""
        mock_eng = MagicMock()
        mock_eng.web_search = AsyncMock(return_value=sample_search_results)

        with patch(_PATCH_TARGET, mock_eng):
            from pds_ultimate.core.business_tools import tool_web_search

            result = await tool_web_search(query="Python tutorial")

            assert result.success is True
            assert result.tool_name == "web_search"
            assert "Python Tutorial" in result.output
            assert "https://python.org/tutorial" in result.output
            assert len(result.data["results"]) == 3

    @pytest.mark.asyncio
    async def test_web_search_empty(self):
        """Пустые результаты."""
        mock_eng = MagicMock()
        mock_eng.web_search = AsyncMock(return_value=[])

        with patch(_PATCH_TARGET, mock_eng):
            from pds_ultimate.core.business_tools import tool_web_search

            result = await tool_web_search(query="xyznonexistent123")

            assert result.success is True
            assert "ничего не найдено" in result.output
            assert result.data["results"] == []

    @pytest.mark.asyncio
    async def test_web_search_error(self):
        """Ошибка при поиске."""
        mock_eng = MagicMock()
        mock_eng.web_search = AsyncMock(
            side_effect=RuntimeError("Browser not started")
        )

        with patch(_PATCH_TARGET, mock_eng):
            from pds_ultimate.core.business_tools import tool_web_search

            result = await tool_web_search(query="test")

            assert result.success is False
            assert "Ошибка" in result.error

    @pytest.mark.asyncio
    async def test_web_search_max_results_clamped(self, sample_search_results):
        """max_results не превышает 20."""
        mock_eng = MagicMock()
        mock_eng.web_search = AsyncMock(return_value=sample_search_results)

        with patch(_PATCH_TARGET, mock_eng):
            from pds_ultimate.core.business_tools import tool_web_search

            await tool_web_search(query="test", max_results=50)

            mock_eng.web_search.assert_called_once_with("test", max_results=20)

    @pytest.mark.asyncio
    async def test_web_search_default_max_results(self, sample_search_results):
        """Дефолтный max_results=10."""
        mock_eng = MagicMock()
        mock_eng.web_search = AsyncMock(return_value=sample_search_results)

        with patch(_PATCH_TARGET, mock_eng):
            from pds_ultimate.core.business_tools import tool_web_search

            await tool_web_search(query="test")

            mock_eng.web_search.assert_called_once_with("test", max_results=10)

    @pytest.mark.asyncio
    async def test_web_search_result_data_structure(self, sample_search_results):
        """Структура данных результата."""
        mock_eng = MagicMock()
        mock_eng.web_search = AsyncMock(return_value=sample_search_results)

        with patch(_PATCH_TARGET, mock_eng):
            from pds_ultimate.core.business_tools import tool_web_search

            result = await tool_web_search(query="Python")

            for r in result.data["results"]:
                assert "title" in r
                assert "url" in r
                assert "snippet" in r

    @pytest.mark.asyncio
    async def test_web_search_snippet_in_output(self, sample_search_results):
        """Сниппеты отображаются в output."""
        mock_eng = MagicMock()
        mock_eng.web_search = AsyncMock(return_value=sample_search_results)

        with patch(_PATCH_TARGET, mock_eng):
            from pds_ultimate.core.business_tools import tool_web_search

            result = await tool_web_search(query="test")

            assert "Learn Python programming" in result.output


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL_OPEN_PAGE
# ═══════════════════════════════════════════════════════════════════════════════


class TestToolOpenPage:
    """Тесты для tool_open_page."""

    @pytest.mark.asyncio
    async def test_open_page_success(self, sample_extracted_data):
        """Успешное открытие страницы."""
        mock_eng = MagicMock()
        mock_eng.extract_data = AsyncMock(return_value=sample_extracted_data)

        with patch(_PATCH_TARGET, mock_eng):
            from pds_ultimate.core.business_tools import tool_open_page

            result = await tool_open_page(url="https://example.com")

            assert result.success is True
            assert result.tool_name == "open_page"
            assert "Example Domain" in result.output
            assert "illustrative" in result.output

    @pytest.mark.asyncio
    async def test_open_page_with_tables(self, sample_extracted_data):
        """Страница с таблицами."""
        mock_eng = MagicMock()
        mock_eng.extract_data = AsyncMock(return_value=sample_extracted_data)

        with patch(_PATCH_TARGET, mock_eng):
            from pds_ultimate.core.business_tools import tool_open_page

            result = await tool_open_page(url="https://example.com")

            assert "таблиц: 1" in result.output
            assert "Header1" in result.output

    @pytest.mark.asyncio
    async def test_open_page_empty(self):
        """Пустая страница."""
        mock_eng = MagicMock()
        mock_eng.extract_data = AsyncMock(
            return_value=ExtractedData(
                url="https://example.com", title="", text=""
            )
        )

        with patch(_PATCH_TARGET, mock_eng):
            from pds_ultimate.core.business_tools import tool_open_page

            result = await tool_open_page(url="https://example.com")

            assert result.success is False
            assert "Не удалось загрузить" in result.error

    @pytest.mark.asyncio
    async def test_open_page_error(self):
        """Ошибка загрузки."""
        mock_eng = MagicMock()
        mock_eng.extract_data = AsyncMock(
            side_effect=Exception("Connection refused")
        )

        with patch(_PATCH_TARGET, mock_eng):
            from pds_ultimate.core.business_tools import tool_open_page

            result = await tool_open_page(url="https://broken.example")

            assert result.success is False
            assert "Ошибка" in result.error

    @pytest.mark.asyncio
    async def test_open_page_long_text_truncated(self):
        """Длинный текст обрезается до 4000 символов."""
        long_text = "x" * 8000
        mock_eng = MagicMock()
        mock_eng.extract_data = AsyncMock(
            return_value=ExtractedData(
                url="https://example.com", title="Long Page", text=long_text
            )
        )

        with patch(_PATCH_TARGET, mock_eng):
            from pds_ultimate.core.business_tools import tool_open_page

            result = await tool_open_page(url="https://example.com")

            assert result.success is True
            assert "ещё 4000 символов" in result.output

    @pytest.mark.asyncio
    async def test_open_page_data_dict(self, sample_extracted_data):
        """data содержит to_dict()."""
        mock_eng = MagicMock()
        mock_eng.extract_data = AsyncMock(return_value=sample_extracted_data)

        with patch(_PATCH_TARGET, mock_eng):
            from pds_ultimate.core.business_tools import tool_open_page

            result = await tool_open_page(url="https://example.com")

            assert "url" in result.data
            assert "title" in result.data
            assert result.data["url"] == "https://example.com"


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL_BROWSER_SCREENSHOT
# ═══════════════════════════════════════════════════════════════════════════════


class TestToolBrowserScreenshot:
    """Тесты для tool_browser_screenshot."""

    @pytest.mark.asyncio
    async def test_screenshot_success(self):
        """Успешный скриншот."""
        mock_eng = MagicMock()
        mock_eng.screenshot = AsyncMock(
            return_value=Path("/tmp/screenshot.png")
        )

        with patch(_PATCH_TARGET, mock_eng):
            from pds_ultimate.core.business_tools import tool_browser_screenshot

            result = await tool_browser_screenshot()

            assert result.success is True
            assert "screenshot.png" in result.output
            assert result.data["path"] == "/tmp/screenshot.png"

    @pytest.mark.asyncio
    async def test_screenshot_full_page(self):
        """Полная страница."""
        mock_eng = MagicMock()
        mock_eng.screenshot = AsyncMock(return_value=Path("/tmp/full.png"))

        with patch(_PATCH_TARGET, mock_eng):
            from pds_ultimate.core.business_tools import tool_browser_screenshot

            await tool_browser_screenshot(full_page=True)

            mock_eng.screenshot.assert_called_once_with(full_page=True)

    @pytest.mark.asyncio
    async def test_screenshot_runtime_error(self):
        """RuntimeError (браузер не запущен)."""
        mock_eng = MagicMock()
        mock_eng.screenshot = AsyncMock(
            side_effect=RuntimeError("Browser not started")
        )

        with patch(_PATCH_TARGET, mock_eng):
            from pds_ultimate.core.business_tools import tool_browser_screenshot

            result = await tool_browser_screenshot()

            assert result.success is False
            assert "Browser not started" in result.error

    @pytest.mark.asyncio
    async def test_screenshot_general_error(self):
        """Общая ошибка."""
        mock_eng = MagicMock()
        mock_eng.screenshot = AsyncMock(side_effect=Exception("Disk full"))

        with patch(_PATCH_TARGET, mock_eng):
            from pds_ultimate.core.business_tools import tool_browser_screenshot

            result = await tool_browser_screenshot()

            assert result.success is False
            assert "Ошибка скриншота" in result.error


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL_BROWSER_CLICK
# ═══════════════════════════════════════════════════════════════════════════════


class TestToolBrowserClick:
    """Тесты для tool_browser_click."""

    @pytest.mark.asyncio
    async def test_click_success(self):
        """Успешный клик."""
        mock_eng = MagicMock()
        mock_eng.click = AsyncMock()
        mock_eng.get_page_info = AsyncMock(
            return_value=PageInfo(
                url="https://example.com/result",
                title="Result Page",
                status=PageStatus.READY,
            )
        )

        with patch(_PATCH_TARGET, mock_eng), \
                patch("pds_ultimate.core.business_tools.asyncio") as mock_aio:
            mock_aio.sleep = AsyncMock()

            from pds_ultimate.core.business_tools import tool_browser_click

            result = await tool_browser_click(selector="#submit-btn")

            assert result.success is True
            assert "Кликнул" in result.output
            assert "#submit-btn" in result.output
            mock_eng.click.assert_called_once_with(
                "#submit-btn", human_like=True
            )

    @pytest.mark.asyncio
    async def test_click_runtime_error(self):
        """RuntimeError (не запущен)."""
        mock_eng = MagicMock()
        mock_eng.click = AsyncMock(side_effect=RuntimeError("Not started"))

        with patch(_PATCH_TARGET, mock_eng):
            from pds_ultimate.core.business_tools import tool_browser_click

            result = await tool_browser_click(selector=".btn")

            assert result.success is False
            assert "Not started" in result.error

    @pytest.mark.asyncio
    async def test_click_general_error(self):
        """Элемент не найден."""
        mock_eng = MagicMock()
        mock_eng.click = AsyncMock(
            side_effect=Exception("Element not found")
        )

        with patch(_PATCH_TARGET, mock_eng):
            from pds_ultimate.core.business_tools import tool_browser_click

            result = await tool_browser_click(selector=".missing")

            assert result.success is False
            assert "Ошибка клика" in result.error


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL_BROWSER_FILL
# ═══════════════════════════════════════════════════════════════════════════════


class TestToolBrowserFill:
    """Тесты для tool_browser_fill."""

    @pytest.mark.asyncio
    async def test_fill_success(self):
        """Успешное заполнение поля."""
        mock_eng = MagicMock()
        mock_eng.fill = AsyncMock()

        with patch(_PATCH_TARGET, mock_eng):
            from pds_ultimate.core.business_tools import tool_browser_fill

            result = await tool_browser_fill(
                selector="#search", value="Python tutorial"
            )

            assert result.success is True
            assert "Заполнил" in result.output
            assert "#search" in result.output
            assert "Python tutorial" in result.output
            mock_eng.fill.assert_called_once_with(
                "#search", "Python tutorial", human_like=True
            )

    @pytest.mark.asyncio
    async def test_fill_long_value_truncated_in_output(self):
        """Длинное значение обрезается в output."""
        mock_eng = MagicMock()
        mock_eng.fill = AsyncMock()

        with patch(_PATCH_TARGET, mock_eng):
            from pds_ultimate.core.business_tools import tool_browser_fill

            long_value = "x" * 200
            result = await tool_browser_fill(
                selector="#text", value=long_value
            )

            assert result.success is True
            assert len(result.output) < 250

    @pytest.mark.asyncio
    async def test_fill_runtime_error(self):
        """RuntimeError."""
        mock_eng = MagicMock()
        mock_eng.fill = AsyncMock(side_effect=RuntimeError("Not started"))

        with patch(_PATCH_TARGET, mock_eng):
            from pds_ultimate.core.business_tools import tool_browser_fill

            result = await tool_browser_fill(
                selector="#input", value="test"
            )

            assert result.success is False

    @pytest.mark.asyncio
    async def test_fill_general_error(self):
        """Element readonly."""
        mock_eng = MagicMock()
        mock_eng.fill = AsyncMock(
            side_effect=Exception("Element is readonly")
        )

        with patch(_PATCH_TARGET, mock_eng):
            from pds_ultimate.core.business_tools import tool_browser_fill

            result = await tool_browser_fill(
                selector="#readonly", value="test"
            )

            assert result.success is False
            assert "Ошибка заполнения" in result.error


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL REGISTRATION
# ═══════════════════════════════════════════════════════════════════════════════


class TestBrowserToolsRegistration:
    """Тесты регистрации browser tools."""

    def test_register_all_includes_browser_tools(self):
        """register_all_tools регистрирует browser tools."""
        from pds_ultimate.core.tools import ToolRegistry

        registry = ToolRegistry()

        from pds_ultimate.core.business_tools import register_all_tools

        with patch("pds_ultimate.core.business_tools.tool_registry", registry):
            count = register_all_tools()
            assert count >= 20  # 16 old + 5 new browser tools

            browser_tools = registry.list_tools(category="browser")
            assert len(browser_tools) == 5

            names = {t.name for t in browser_tools}
            assert "web_search" in names
            assert "open_page" in names
            assert "browser_screenshot" in names
            assert "browser_click" in names
            assert "browser_fill" in names

    def test_web_search_tool_schema(self):
        """Schema для web_search содержит правильные параметры."""
        from pds_ultimate.core.tools import ToolRegistry

        registry = ToolRegistry()

        from pds_ultimate.core.business_tools import register_all_tools

        with patch("pds_ultimate.core.business_tools.tool_registry", registry):
            register_all_tools()
            tool = registry.get("web_search")
            assert tool is not None
            assert tool.category == "browser"

            schema = tool.to_json_schema()
            func = schema["function"]
            params = func["parameters"]["properties"]
            assert "query" in params
            assert "max_results" in params
            assert "query" in func["parameters"]["required"]

    def test_open_page_tool_has_url_param(self):
        """open_page имеет обязательный параметр url."""
        from pds_ultimate.core.tools import ToolRegistry

        registry = ToolRegistry()

        from pds_ultimate.core.business_tools import register_all_tools

        with patch("pds_ultimate.core.business_tools.tool_registry", registry):
            register_all_tools()
            tool = registry.get("open_page")
            assert tool is not None

            schema = tool.to_json_schema()
            assert "url" in schema["function"]["parameters"]["required"]

    def test_browser_click_tool_has_selector(self):
        """browser_click имеет обязательный selector."""
        from pds_ultimate.core.tools import ToolRegistry

        registry = ToolRegistry()

        from pds_ultimate.core.business_tools import register_all_tools

        with patch("pds_ultimate.core.business_tools.tool_registry", registry):
            register_all_tools()
            tool = registry.get("browser_click")
            assert tool is not None

            schema = tool.to_json_schema()
            assert "selector" in schema["function"]["parameters"]["required"]

    def test_browser_fill_tool_has_both_params(self):
        """browser_fill имеет selector и value."""
        from pds_ultimate.core.tools import ToolRegistry

        registry = ToolRegistry()

        from pds_ultimate.core.business_tools import register_all_tools

        with patch("pds_ultimate.core.business_tools.tool_registry", registry):
            register_all_tools()
            tool = registry.get("browser_fill")
            assert tool is not None

            schema = tool.to_json_schema()
            required = schema["function"]["parameters"]["required"]
            assert "selector" in required
            assert "value" in required

    def test_browser_screenshot_optional_param(self):
        """browser_screenshot: full_page опционален."""
        from pds_ultimate.core.tools import ToolRegistry

        registry = ToolRegistry()

        from pds_ultimate.core.business_tools import register_all_tools

        with patch("pds_ultimate.core.business_tools.tool_registry", registry):
            register_all_tools()
            tool = registry.get("browser_screenshot")
            assert tool is not None

            schema = tool.to_json_schema()
            required = schema["function"]["parameters"].get("required", [])
            assert "full_page" not in required


# ═══════════════════════════════════════════════════════════════════════════════
# INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════════


class TestBrowserToolsIntegration:
    """Интеграционные тесты browser tools."""

    @pytest.mark.asyncio
    async def test_search_then_open(
        self, sample_search_results, sample_extracted_data
    ):
        """Сценарий: поиск → открытие первого результата."""
        mock_eng = MagicMock()
        mock_eng.web_search = AsyncMock(return_value=sample_search_results)
        mock_eng.extract_data = AsyncMock(return_value=sample_extracted_data)

        with patch(_PATCH_TARGET, mock_eng):
            from pds_ultimate.core.business_tools import (
                tool_open_page,
                tool_web_search,
            )

            # Шаг 1: поиск
            search_result = await tool_web_search(query="Python")
            assert search_result.success is True

            # Шаг 2: открытие первой ссылки
            first_url = search_result.data["results"][0]["url"]
            page_result = await tool_open_page(url=first_url)
            assert page_result.success is True
            assert "Example Domain" in page_result.output

    @pytest.mark.asyncio
    async def test_fill_and_click(self):
        """Сценарий: заполнить форму → кликнуть."""
        mock_eng = MagicMock()
        mock_eng.fill = AsyncMock()
        mock_eng.click = AsyncMock()
        mock_eng.get_page_info = AsyncMock(
            return_value=PageInfo(
                url="https://example.com/results",
                title="Search Results",
                status=PageStatus.READY,
            )
        )

        with patch(_PATCH_TARGET, mock_eng), \
                patch("pds_ultimate.core.business_tools.asyncio") as mock_aio:
            mock_aio.sleep = AsyncMock()

            from pds_ultimate.core.business_tools import (
                tool_browser_click,
                tool_browser_fill,
            )

            fill_result = await tool_browser_fill(
                selector="#search-input", value="Python"
            )
            assert fill_result.success is True

            click_result = await tool_browser_click(selector="#search-btn")
            assert click_result.success is True
            assert "Search Results" in click_result.output

    @pytest.mark.asyncio
    async def test_all_tools_return_tool_result(self):
        """Все browser tools возвращают ToolResult."""
        mock_eng = MagicMock()
        mock_eng.web_search = AsyncMock(return_value=[])
        mock_eng.extract_data = AsyncMock(
            return_value=ExtractedData(
                url="https://example.com", title="Title", text="Some text"
            )
        )
        mock_eng.screenshot = AsyncMock(return_value=Path("/tmp/shot.png"))
        mock_eng.click = AsyncMock()
        mock_eng.get_page_info = AsyncMock(
            return_value=PageInfo(
                url="https://example.com",
                title="Title",
                status=PageStatus.READY,
            )
        )
        mock_eng.fill = AsyncMock()

        with patch(_PATCH_TARGET, mock_eng), \
                patch("pds_ultimate.core.business_tools.asyncio") as mock_aio:
            mock_aio.sleep = AsyncMock()

            from pds_ultimate.core.business_tools import (
                tool_browser_click,
                tool_browser_fill,
                tool_browser_screenshot,
                tool_open_page,
                tool_web_search,
            )

            results = await asyncio.gather(
                tool_web_search(query="test"),
                tool_open_page(url="https://example.com"),
                tool_browser_screenshot(),
                tool_browser_click(selector=".btn"),
                tool_browser_fill(selector="#in", value="v"),
            )

            for r in results:
                assert isinstance(r, ToolResult)
                assert isinstance(r.tool_name, str)
                assert isinstance(r.success, bool)
