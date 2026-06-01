"""
PDS-Ultimate Browser Engine Tests (Part 4)
=============================================
Тесты браузерного движка.

Тестируем (без реального браузера — unit tests):
1. BrowserConfig — конфигурация
2. PageInfo, ExtractedData, SearchResult — модели данных
3. HumanBehavior — human-like поведение (delays, randomness)
4. BrowserEngine — lifecycle, state, stats
5. BrowserStats — статистика
6. Stealth — JS stealth script
7. User Agents — пул UA
8. Edge Cases — граничные случаи
"""

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from pds_ultimate.core.browser_engine import (
    SCREEN_SIZES,
    STEALTH_JS,
    USER_AGENTS,
    BrowserEngine,
    BrowserStats,
    ExtractedData,
    HumanBehavior,
    PageInfo,
    PageStatus,
    SearchResult,
)

# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def human():
    """Fresh HumanBehavior."""
    return HumanBehavior(
        min_type_delay=10,
        max_type_delay=20,
        min_click_delay=10,
        max_click_delay=50,
    )


@pytest.fixture
def stats():
    """Fresh BrowserStats."""
    return BrowserStats()


@pytest.fixture
def engine():
    """BrowserEngine without starting (no real browser)."""
    return BrowserEngine()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. BROWSER CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class TestBrowserConfig:
    """Тесты конфигурации браузера."""

    def test_config_exists(self):
        """BrowserConfig доступен в AppConfig."""
        from pds_ultimate.config import config
        assert hasattr(config, 'browser')
        assert config.browser is not None

    def test_default_values(self):
        """Дефолтные значения."""
        from pds_ultimate.config import BrowserConfig
        cfg = BrowserConfig()
        assert cfg.headless is True
        assert cfg.browser_type == "chromium"
        assert cfg.viewport_width == 1920
        assert cfg.viewport_height == 1080
        assert cfg.default_timeout == 30000
        assert cfg.navigation_timeout == 60000
        assert cfg.max_pages == 5
        assert cfg.stealth_enabled is True
        assert cfg.locale == "en-US"
        assert cfg.timezone == "Asia/Ashgabat"

    def test_human_like_delays(self):
        """Настройки задержек."""
        from pds_ultimate.config import BrowserConfig
        cfg = BrowserConfig()
        assert cfg.min_type_delay == 50
        assert cfg.max_type_delay == 150
        assert cfg.min_click_delay == 100
        assert cfg.max_click_delay == 500

    def test_directories(self):
        """Директории для скриншотов и загрузок."""
        from pds_ultimate.config import BrowserConfig
        cfg = BrowserConfig()
        assert isinstance(cfg.screenshots_dir, Path)
        assert isinstance(cfg.downloads_dir, Path)

    def test_proxy_default_empty(self):
        """Прокси по умолчанию пустой."""
        from pds_ultimate.config import BrowserConfig
        cfg = BrowserConfig()
        assert cfg.proxy_server == ""

    def test_user_agent_default_empty(self):
        """User-Agent по умолчанию пустой (рандомный)."""
        from pds_ultimate.config import BrowserConfig
        cfg = BrowserConfig()
        assert cfg.user_agent == ""


# ═══════════════════════════════════════════════════════════════════════════════
# 2. PAGE INFO
# ═══════════════════════════════════════════════════════════════════════════════

class TestPageInfo:
    """Тесты информации о странице."""

    def test_create_default(self):
        """Создание с дефолтами."""
        pi = PageInfo(url="https://example.com")
        assert pi.url == "https://example.com"
        assert pi.title == ""
        assert pi.status_code == 200
        assert pi.status == PageStatus.READY
        assert pi.load_time_ms == 0

    def test_create_full(self):
        """Создание со всеми полями."""
        pi = PageInfo(
            url="https://example.com",
            title="Example",
            status_code=200,
            status=PageStatus.READY,
            load_time_ms=500,
            content_type="text/html",
            text_length=1000,
        )
        assert pi.title == "Example"
        assert pi.load_time_ms == 500
        assert pi.content_type == "text/html"

    def test_error_status(self):
        """Страница с ошибкой."""
        pi = PageInfo(url="https://bad.com",
                      status=PageStatus.ERROR, status_code=0)
        assert pi.status == PageStatus.ERROR
        assert pi.status_code == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 3. EXTRACTED DATA
# ═══════════════════════════════════════════════════════════════════════════════

class TestExtractedData:
    """Тесты извлечённых данных."""

    def test_create_empty(self):
        """Пустые данные."""
        data = ExtractedData(url="https://example.com")
        assert data.url == "https://example.com"
        assert data.text == ""
        assert data.links == []
        assert data.tables == []
        assert data.images == []
        assert data.meta == {}
        assert data.headings == []

    def test_summary_short(self):
        """Краткое summary."""
        data = ExtractedData(
            url="https://example.com",
            title="Test Page",
            text="Hello world",
            links=[{"url": "https://a.com", "text": "Link A"}],
            tables=[[[" cell"]]],
            images=[{"src": "img.png", "alt": ""}],
        )
        summary = data.summary()
        assert "Test Page" in summary
        assert "https://example.com" in summary
        assert "Hello world" in summary
        assert "Ссылок: 1" in summary
        assert "Таблиц: 1" in summary
        assert "Изображений: 1" in summary

    def test_summary_truncation(self):
        """Обрезка длинного текста в summary."""
        long_text = "A" * 5000
        data = ExtractedData(url="https://x.com", text=long_text)
        summary = data.summary(max_text=100)
        assert len(summary) < 5000
        assert "..." in summary

    def test_to_dict(self):
        """Сериализация."""
        data = ExtractedData(
            url="https://example.com",
            title="Test",
            text="Hello",
            links=[{"url": "a", "text": "b"}],
            tables=[[["c"]]],
            images=[{"src": "d", "alt": "e"}],
            meta={"description": "test"},
        )
        d = data.to_dict()
        assert d["url"] == "https://example.com"
        assert d["title"] == "Test"
        assert d["text_length"] == 5
        assert d["links_count"] == 1
        assert d["tables_count"] == 1
        assert d["images_count"] == 1
        assert d["meta"]["description"] == "test"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. SEARCH RESULT
# ═══════════════════════════════════════════════════════════════════════════════

class TestSearchResult:
    """Тесты результата поиска."""

    def test_create(self):
        """Создание."""
        sr = SearchResult(
            title="Python Tutorial",
            url="https://python.org",
            snippet="Learn Python programming",
            position=1,
        )
        assert sr.title == "Python Tutorial"
        assert sr.url == "https://python.org"
        assert sr.position == 1

    def test_str(self):
        """Строковое представление."""
        sr = SearchResult(title="Test", url="https://t.com",
                          snippet="Desc", position=3)
        text = str(sr)
        assert "[3]" in text
        assert "Test" in text
        assert "https://t.com" in text
        assert "Desc" in text


# ═══════════════════════════════════════════════════════════════════════════════
# 5. BROWSER STATS
# ═══════════════════════════════════════════════════════════════════════════════

class TestBrowserStats:
    """Тесты статистики."""

    def test_initial(self, stats):
        """Начальные значения."""
        assert stats.pages_loaded == 0
        assert stats.pages_failed == 0
        assert stats.screenshots_taken == 0
        assert stats.searches_performed == 0
        assert stats.total_bytes_downloaded == 0
        assert stats.errors == []

    def test_increment(self, stats):
        """Инкрементация счётчиков."""
        stats.pages_loaded += 5
        stats.pages_failed += 1
        stats.screenshots_taken += 2
        stats.searches_performed += 3
        stats.total_bytes_downloaded += 1024
        stats.errors.append("test error")

        assert stats.pages_loaded == 5
        assert stats.pages_failed == 1
        assert stats.screenshots_taken == 2
        assert stats.errors == ["test error"]

    def test_to_dict(self, stats):
        """Сериализация."""
        stats.pages_loaded = 10
        stats.errors.append("err1")
        stats.errors.append("err2")

        d = stats.to_dict()
        assert d["pages_loaded"] == 10
        assert d["errors_count"] == 2
        assert "bytes_downloaded" in d


# ═══════════════════════════════════════════════════════════════════════════════
# 6. PAGE STATUS ENUM
# ═══════════════════════════════════════════════════════════════════════════════

class TestPageStatus:
    """Тесты статусов страницы."""

    def test_values(self):
        """Все статусы определены."""
        assert PageStatus.LOADING == "loading"
        assert PageStatus.READY == "ready"
        assert PageStatus.ERROR == "error"
        assert PageStatus.CLOSED == "closed"

    def test_all_statuses(self):
        """Количество статусов."""
        assert len(list(PageStatus)) == 4


# ═══════════════════════════════════════════════════════════════════════════════
# 7. HUMAN BEHAVIOR
# ═══════════════════════════════════════════════════════════════════════════════

class TestHumanBehavior:
    """Тесты human-like поведения."""

    def test_create(self, human):
        """Создание."""
        assert human.min_type_delay == 10
        assert human.max_type_delay == 20
        assert human.min_click_delay == 10
        assert human.max_click_delay == 50

    @pytest.mark.asyncio
    async def test_random_delay(self, human):
        """Случайная задержка выполняется."""
        start = time.time()
        await human.random_delay(50, 100)
        elapsed = time.time() - start
        assert elapsed >= 0.04  # Минимум ~50ms (с допуском)
        assert elapsed < 0.5    # Не более 500ms

    @pytest.mark.asyncio
    async def test_thinking_pause(self, human):
        """Пауза на 'подумать'."""
        start = time.time()
        await human.thinking_pause()
        elapsed = time.time() - start
        assert elapsed >= 0.4  # Минимум ~0.5s (с допуском)
        assert elapsed < 3.0   # Максимум ~2s (с допуском)

    def test_random_user_agent(self, human):
        """Случайный User-Agent."""
        ua = human.get_random_user_agent()
        assert ua in USER_AGENTS
        assert "Mozilla" in ua

    def test_random_user_agent_variety(self, human):
        """Разные UA при повторных вызовах."""
        agents = {human.get_random_user_agent() for _ in range(50)}
        assert len(agents) > 1  # Должны быть разные

    def test_random_screen_size(self, human):
        """Случайное разрешение экрана."""
        size = human.get_random_screen_size()
        assert size in SCREEN_SIZES
        assert isinstance(size, tuple)
        assert len(size) == 2
        assert size[0] > 0 and size[1] > 0

    def test_screen_size_variety(self, human):
        """Разные разрешения при повторных вызовах."""
        sizes = {human.get_random_screen_size() for _ in range(50)}
        assert len(sizes) > 1


# ═══════════════════════════════════════════════════════════════════════════════
# 8. USER AGENTS POOL
# ═══════════════════════════════════════════════════════════════════════════════

class TestUserAgents:
    """Тесты пула User-Agent'ов."""

    def test_pool_not_empty(self):
        """Пул не пустой."""
        assert len(USER_AGENTS) > 0

    def test_all_valid_format(self):
        """Все UA начинаются с Mozilla."""
        for ua in USER_AGENTS:
            assert ua.startswith("Mozilla/5.0"), f"Invalid UA: {ua}"

    def test_contains_chrome(self):
        """Есть Chrome UA."""
        chrome_uas = [ua for ua in USER_AGENTS if "Chrome" in ua]
        assert len(chrome_uas) > 0

    def test_contains_firefox(self):
        """Есть Firefox UA."""
        firefox_uas = [ua for ua in USER_AGENTS if "Firefox" in ua]
        assert len(firefox_uas) > 0

    def test_contains_different_os(self):
        """Есть UA для разных ОС."""
        windows = any("Windows" in ua for ua in USER_AGENTS)
        mac = any("Macintosh" in ua for ua in USER_AGENTS)
        linux = any("Linux" in ua for ua in USER_AGENTS)
        assert windows and mac and linux


# ═══════════════════════════════════════════════════════════════════════════════
# 9. SCREEN SIZES
# ═══════════════════════════════════════════════════════════════════════════════

class TestScreenSizes:
    """Тесты разрешений экрана."""

    def test_pool_not_empty(self):
        """Пул не пустой."""
        assert len(SCREEN_SIZES) > 0

    def test_all_tuples(self):
        """Все элементы — кортежи (w, h)."""
        for size in SCREEN_SIZES:
            assert isinstance(size, tuple)
            assert len(size) == 2
            assert size[0] > 0 and size[1] > 0

    def test_contains_fullhd(self):
        """Есть Full HD."""
        assert (1920, 1080) in SCREEN_SIZES

    def test_landscape_orientation(self):
        """Все горизонтальные (w > h)."""
        for w, h in SCREEN_SIZES:
            assert w > h, f"Not landscape: {w}x{h}"


# ═══════════════════════════════════════════════════════════════════════════════
# 10. STEALTH JS
# ═══════════════════════════════════════════════════════════════════════════════

class TestStealthJS:
    """Тесты stealth-скрипта."""

    def test_not_empty(self):
        """Скрипт не пустой."""
        assert len(STEALTH_JS) > 100

    def test_hides_webdriver(self):
        """Скрывает navigator.webdriver."""
        assert "webdriver" in STEALTH_JS

    def test_adds_chrome_runtime(self):
        """Добавляет chrome.runtime."""
        assert "chrome" in STEALTH_JS
        assert "runtime" in STEALTH_JS

    def test_overrides_plugins(self):
        """Подменяет navigator.plugins."""
        assert "plugins" in STEALTH_JS

    def test_overrides_languages(self):
        """Подменяет navigator.languages."""
        assert "languages" in STEALTH_JS

    def test_overrides_webgl(self):
        """Подменяет WebGL vendor."""
        assert "WebGLRenderingContext" in STEALTH_JS

    def test_overrides_permissions(self):
        """Подменяет permissions.query."""
        assert "permissions" in STEALTH_JS

    def test_overrides_hardware(self):
        """Подменяет hardwareConcurrency."""
        assert "hardwareConcurrency" in STEALTH_JS


# ═══════════════════════════════════════════════════════════════════════════════
# 11. BROWSER ENGINE — Unit Tests (без реального браузера)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBrowserEngine:
    """Тесты движка (без Playwright)."""

    def test_create_engine(self, engine):
        """Создание движка."""
        assert engine.is_started is False
        assert engine.current_url == ""
        assert engine.stats.pages_loaded == 0

    def test_initial_stats(self, engine):
        """Начальная статистика."""
        s = engine.stats
        assert s.pages_loaded == 0
        assert s.pages_failed == 0
        assert s.searches_performed == 0
        assert s.errors == []

    def test_stats_summary(self, engine):
        """Текстовая сводка."""
        summary = engine.get_stats_summary()
        assert "Browser Stats" in summary
        assert "Pages loaded: 0" in summary

    def test_global_instance(self):
        """Глобальный экземпляр."""
        from pds_ultimate.core.browser_engine import browser_engine
        assert browser_engine is not None
        assert isinstance(browser_engine, BrowserEngine)

    @pytest.mark.asyncio
    async def test_extract_text_not_started(self, engine):
        """Извлечение текста без запуска → пустая строка."""
        text = await engine.extract_text()
        assert text == ""

    @pytest.mark.asyncio
    async def test_query_selector_not_started(self, engine):
        """Query selector без запуска → False."""
        result = await engine.query_selector("div")
        assert result is False

    @pytest.mark.asyncio
    async def test_wait_for_not_started(self, engine):
        """Wait for без запуска → False."""
        result = await engine.wait_for("div")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_attribute_not_started(self, engine):
        """Get attribute без запуска → None."""
        result = await engine.get_attribute("a", "href")
        assert result is None

    @pytest.mark.asyncio
    async def test_evaluate_not_started(self, engine):
        """Evaluate JS без запуска → None."""
        result = await engine.evaluate("1 + 1")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_html_not_started(self, engine):
        """Get HTML без запуска → пустая строка."""
        html = await engine.get_html()
        assert html == ""

    @pytest.mark.asyncio
    async def test_get_page_info_not_started(self, engine):
        """Page info без запуска → CLOSED."""
        info = await engine.get_page_info()
        assert info.status == PageStatus.CLOSED
        assert info.url == ""

    @pytest.mark.asyncio
    async def test_go_back_not_started(self, engine):
        """Go back без запуска."""
        info = await engine.go_back()
        assert info.status == PageStatus.ERROR

    @pytest.mark.asyncio
    async def test_go_forward_not_started(self, engine):
        """Go forward без запуска."""
        info = await engine.go_forward()
        assert info.status == PageStatus.ERROR

    @pytest.mark.asyncio
    async def test_scroll_not_started(self, engine):
        """Scroll без запуска — не падает."""
        await engine.scroll_down()
        await engine.scroll_up()

    @pytest.mark.asyncio
    async def test_press_key_not_started(self, engine):
        """Press key без запуска — не падает."""
        await engine.press_key("Enter")

    @pytest.mark.asyncio
    async def test_screenshot_not_started(self, engine):
        """Screenshot без запуска → RuntimeError."""
        with pytest.raises(RuntimeError, match="Browser not started"):
            await engine.screenshot()

    @pytest.mark.asyncio
    async def test_fill_not_started(self, engine):
        """Fill без запуска → RuntimeError."""
        with pytest.raises(RuntimeError, match="Browser not started"):
            await engine.fill("input", "test")

    @pytest.mark.asyncio
    async def test_click_not_started(self, engine):
        """Click без запуска → RuntimeError."""
        with pytest.raises(RuntimeError, match="Browser not started"):
            await engine.click("button")

    @pytest.mark.asyncio
    async def test_select_option_not_started(self, engine):
        """Select option без запуска → RuntimeError."""
        with pytest.raises(RuntimeError, match="Browser not started"):
            await engine.select_option("select", "value")

    @pytest.mark.asyncio
    async def test_check_not_started(self, engine):
        """Check без запуска → RuntimeError."""
        with pytest.raises(RuntimeError, match="Browser not started"):
            await engine.check("input")

    @pytest.mark.asyncio
    async def test_uncheck_not_started(self, engine):
        """Uncheck без запуска → RuntimeError."""
        with pytest.raises(RuntimeError, match="Browser not started"):
            await engine.uncheck("input")

    @pytest.mark.asyncio
    async def test_save_cookies_not_started(self, engine):
        """Save cookies без запуска → RuntimeError."""
        with pytest.raises(RuntimeError, match="Browser not started"):
            await engine.save_cookies()

    @pytest.mark.asyncio
    async def test_load_cookies_not_started(self, engine):
        """Load cookies без запуска → RuntimeError."""
        with pytest.raises(RuntimeError, match="Browser not started"):
            await engine.load_cookies("/tmp/cookies.json")

    @pytest.mark.asyncio
    async def test_clear_cookies_not_started(self, engine):
        """Clear cookies без запуска — не падает."""
        await engine.clear_cookies()

    @pytest.mark.asyncio
    async def test_save_session_not_started(self, engine):
        """Save session без запуска → RuntimeError."""
        with pytest.raises(RuntimeError, match="Browser not started"):
            await engine.save_session()

    @pytest.mark.asyncio
    async def test_download_not_started(self, engine):
        """Download без запуска → RuntimeError."""
        with pytest.raises(RuntimeError, match="Browser not started"):
            await engine.download_file("https://example.com/file.zip")

    @pytest.mark.asyncio
    async def test_new_page_not_started(self, engine):
        """New page без запуска → RuntimeError."""
        with pytest.raises(RuntimeError, match="Browser not started"):
            await engine.new_page()

    @pytest.mark.asyncio
    async def test_switch_page_nonexistent(self, engine):
        """Switch page несуществующей → False."""
        result = await engine.switch_page("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_close_page_nonexistent(self, engine):
        """Close page несуществующей — не падает."""
        await engine.close_page("nonexistent")

    @pytest.mark.asyncio
    async def test_stop_not_started(self, engine):
        """Stop без запуска — не падает."""
        await engine.stop()
        assert engine.is_started is False

    @pytest.mark.asyncio
    async def test_extract_data_not_started(self, engine):
        """Extract data без запуска — пустые данные."""
        data = await engine.extract_data()
        assert data.url == ""

    @pytest.mark.asyncio
    async def test_extract_links_not_started(self, engine):
        """Extract links без запуска — пустой список."""
        links = await engine.extract_links()
        assert links == []


# ═══════════════════════════════════════════════════════════════════════════════
# 12. BROWSER ENGINE — Mock Tests (имитация Playwright)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBrowserEngineMocked:
    """Тесты с мок-объектами Playwright."""

    @pytest.fixture
    def mock_engine(self):
        """Engine с замоканным Playwright."""
        eng = BrowserEngine()
        eng._started = True

        # Mock page
        mock_page = AsyncMock()
        mock_page.url = "https://example.com"
        mock_page.title = AsyncMock(return_value="Example Domain")
        mock_page.goto = AsyncMock(return_value=MagicMock(
            status=200, headers={"content-type": "text/html"}
        ))
        mock_page.evaluate = AsyncMock(return_value="")
        mock_page.content = AsyncMock(return_value="<html></html>")
        mock_page.screenshot = AsyncMock()
        mock_page.locator = MagicMock()
        mock_page.keyboard = MagicMock()
        mock_page.keyboard.press = AsyncMock()
        mock_page.mouse = MagicMock()
        mock_page.mouse.wheel = AsyncMock()
        mock_page.fill = AsyncMock()
        mock_page.click = AsyncMock()
        mock_page.select_option = AsyncMock()
        mock_page.check = AsyncMock()
        mock_page.uncheck = AsyncMock()
        mock_page.close = AsyncMock()
        mock_page.set_default_timeout = MagicMock()
        mock_page.set_default_navigation_timeout = MagicMock()

        eng._page = mock_page
        eng._last_title = "Example Domain"

        # Mock context
        mock_context = AsyncMock()
        mock_context.cookies = AsyncMock(return_value=[])
        mock_context.add_cookies = AsyncMock()
        mock_context.clear_cookies = AsyncMock()
        mock_context.storage_state = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_context.close = AsyncMock()
        eng._context = mock_context

        # Mock browser
        eng._browser = AsyncMock()
        eng._browser.close = AsyncMock()

        # Mock playwright
        eng._playwright = AsyncMock()
        eng._playwright.stop = AsyncMock()

        return eng

    @pytest.mark.asyncio
    async def test_goto_success(self, mock_engine):
        """Успешная навигация."""
        info = await mock_engine.goto("https://example.com")
        assert info.status == PageStatus.READY
        assert info.status_code == 200
        assert info.title == "Example Domain"
        assert mock_engine.stats.pages_loaded == 1

    @pytest.mark.asyncio
    async def test_goto_error(self, mock_engine):
        """Ошибка навигации."""
        mock_engine._page.goto = AsyncMock(side_effect=Exception("Timeout"))
        info = await mock_engine.goto("https://bad.com")
        assert info.status == PageStatus.ERROR
        assert mock_engine.stats.pages_failed == 1
        assert len(mock_engine.stats.errors) == 1

    @pytest.mark.asyncio
    async def test_get_page_info(self, mock_engine):
        """Информация о текущей странице."""
        info = await mock_engine.get_page_info()
        assert info.url == "https://example.com"
        assert info.title == "Example Domain"
        assert info.status == PageStatus.READY

    @pytest.mark.asyncio
    async def test_evaluate(self, mock_engine):
        """Выполнение JavaScript."""
        mock_engine._page.evaluate = AsyncMock(return_value=42)
        result = await mock_engine.evaluate("21 * 2")
        assert result == 42

    @pytest.mark.asyncio
    async def test_get_html(self, mock_engine):
        """Получение HTML."""
        html = await mock_engine.get_html()
        assert html == "<html></html>"

    @pytest.mark.asyncio
    async def test_press_key(self, mock_engine):
        """Нажатие клавиши."""
        await mock_engine.press_key("Enter")
        mock_engine._page.keyboard.press.assert_called_once_with("Enter")

    @pytest.mark.asyncio
    async def test_fill_not_human(self, mock_engine):
        """Заполнение поля (не human-like)."""
        await mock_engine.fill("input", "test", human_like=False)
        mock_engine._page.fill.assert_called_once_with("input", "test")

    @pytest.mark.asyncio
    async def test_click_not_human(self, mock_engine):
        """Клик (не human-like)."""
        await mock_engine.click("button", human_like=False)
        mock_engine._page.click.assert_called_once_with("button")

    @pytest.mark.asyncio
    async def test_select_option(self, mock_engine):
        """Выбор опции."""
        await mock_engine.select_option("select", "value1")
        mock_engine._page.select_option.assert_called_once_with(
            "select", "value1")

    @pytest.mark.asyncio
    async def test_check_uncheck(self, mock_engine):
        """Check/Uncheck."""
        await mock_engine.check("input")
        mock_engine._page.check.assert_called_once_with("input")
        await mock_engine.uncheck("input")
        mock_engine._page.uncheck.assert_called_once_with("input")

    @pytest.mark.asyncio
    async def test_clear_cookies(self, mock_engine):
        """Очистка cookies."""
        await mock_engine.clear_cookies()
        mock_engine._context.clear_cookies.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop(self, mock_engine):
        """Остановка браузера."""
        browser_mock = mock_engine._browser
        playwright_mock = mock_engine._playwright
        await mock_engine.stop()
        assert mock_engine.is_started is False
        browser_mock.close.assert_called_once()
        playwright_mock.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_switch_page(self, mock_engine):
        """Переключение страницы."""
        # Нет страниц
        assert await mock_engine.switch_page("p1") is False

        # Добавляем
        mock_page = AsyncMock()
        mock_engine._pages["p1"] = mock_page
        assert await mock_engine.switch_page("p1") is True
        assert mock_engine._page is mock_page

    @pytest.mark.asyncio
    async def test_close_page(self, mock_engine):
        """Закрытие страницы."""
        mock_page = AsyncMock()
        mock_engine._pages["p1"] = mock_page
        await mock_engine.close_page("p1")
        assert "p1" not in mock_engine._pages

    @pytest.mark.asyncio
    async def test_current_url(self, mock_engine):
        """Текущий URL."""
        assert mock_engine.current_url == "https://example.com"

    def test_current_title(self, mock_engine):
        """Текущий заголовок."""
        assert mock_engine.current_title == "Example Domain"

    @pytest.mark.asyncio
    async def test_stats_after_operations(self, mock_engine):
        """Статистика после операций."""
        await mock_engine.goto("https://a.com")
        await mock_engine.goto("https://b.com")
        assert mock_engine.stats.pages_loaded == 2

        mock_engine._page.goto = AsyncMock(side_effect=Exception("err"))
        await mock_engine.goto("https://c.com")
        assert mock_engine.stats.pages_failed == 1

    @pytest.mark.asyncio
    async def test_reload(self, mock_engine):
        """Перезагрузка страницы."""
        info = await mock_engine.reload()
        assert info.status == PageStatus.READY

    @pytest.mark.asyncio
    async def test_query_selector_found(self, mock_engine):
        """Элемент найден."""
        locator_mock = MagicMock()
        locator_mock.count = AsyncMock(return_value=3)
        mock_engine._page.locator = MagicMock(return_value=locator_mock)

        assert await mock_engine.query_selector("div.test") is True

    @pytest.mark.asyncio
    async def test_query_selector_not_found(self, mock_engine):
        """Элемент не найден."""
        locator_mock = MagicMock()
        locator_mock.count = AsyncMock(return_value=0)
        mock_engine._page.locator = MagicMock(return_value=locator_mock)

        assert await mock_engine.query_selector("div.missing") is False


# ═══════════════════════════════════════════════════════════════════════════════
# 13. EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Граничные случаи."""

    def test_extracted_data_empty_summary(self):
        """Пустые данные — summary без ошибок."""
        data = ExtractedData(url="")
        summary = data.summary()
        assert isinstance(summary, str)

    def test_search_result_empty(self):
        """Пустой результат поиска."""
        sr = SearchResult(title="", url="", snippet="", position=0)
        text = str(sr)
        assert "[0]" in text

    def test_page_info_all_statuses(self):
        """Все статусы PageInfo."""
        for status in PageStatus:
            pi = PageInfo(url="test", status=status)
            assert pi.status == status

    def test_stats_many_errors(self):
        """Множество ошибок в статистике."""
        s = BrowserStats()
        for i in range(100):
            s.errors.append(f"Error {i}")
        d = s.to_dict()
        assert d["errors_count"] == 100

    def test_human_behavior_default_params(self):
        """HumanBehavior с дефолтами."""
        h = HumanBehavior()
        assert h.min_type_delay == 50
        assert h.max_type_delay == 150

    @pytest.mark.asyncio
    async def test_double_stop(self):
        """Двойной stop — не падает."""
        eng = BrowserEngine()
        await eng.stop()
        await eng.stop()
        assert eng.is_started is False

    @pytest.mark.asyncio
    async def test_engine_context_manager_not_started(self):
        """Context manager без реального Playwright — ошибка старта."""
        # Без установленного Playwright, start() вызовет RuntimeError
        eng = BrowserEngine()
        try:
            async with eng:
                pass
        except RuntimeError:
            pass  # Expected — Playwright не установлен
        assert eng.is_started is False

    def test_user_agents_unique(self):
        """Все UA уникальные."""
        assert len(USER_AGENTS) == len(set(USER_AGENTS))

    def test_screen_sizes_unique(self):
        """Все размеры уникальные."""
        assert len(SCREEN_SIZES) == len(set(SCREEN_SIZES))
