"""
Тесты Part 7 Business Tools — новые tool-handlers в business_tools.py
"""

from unittest.mock import patch

import pytest


class TestPart7ToolRegistration:
    """Тесты регистрации Part 7 инструментов."""

    def test_register_all_tools_count(self):
        """register_all_tools: Part 7 увеличил кол-во tools."""
        from pds_ultimate.core.business_tools import register_all_tools
        from pds_ultimate.core.tools import tool_registry

        # Очищаем и регистрируем
        tool_registry._tools.clear()
        count = register_all_tools()
        assert count >= 25  # Было ~20, добавили ~7

    def test_exchange_rates_registered(self):
        """exchange_rates зарегистрирован."""
        from pds_ultimate.core.business_tools import register_all_tools
        from pds_ultimate.core.tools import tool_registry

        tool_registry._tools.clear()
        register_all_tools()
        tool = tool_registry.get("exchange_rates")
        assert tool is not None
        assert tool.category == "finance"

    def test_ocr_recognize_registered(self):
        """ocr_recognize зарегистрирован."""
        from pds_ultimate.core.business_tools import register_all_tools
        from pds_ultimate.core.tools import tool_registry

        tool_registry._tools.clear()
        register_all_tools()
        tool = tool_registry.get("ocr_recognize")
        assert tool is not None
        assert tool.category == "files"

    def test_convert_file_registered(self):
        """convert_file зарегистрирован."""
        from pds_ultimate.core.business_tools import register_all_tools
        from pds_ultimate.core.tools import tool_registry

        tool_registry._tools.clear()
        register_all_tools()
        tool = tool_registry.get("convert_file")
        assert tool is not None

    def test_scan_receipt_registered(self):
        """scan_receipt зарегистрирован."""
        from pds_ultimate.core.business_tools import register_all_tools
        from pds_ultimate.core.tools import tool_registry

        tool_registry._tools.clear()
        register_all_tools()
        tool = tool_registry.get("scan_receipt")
        assert tool is not None
        assert tool.needs_db is True

    def test_translate_text_registered(self):
        """translate_text зарегистрирован."""
        from pds_ultimate.core.business_tools import register_all_tools
        from pds_ultimate.core.tools import tool_registry

        tool_registry._tools.clear()
        register_all_tools()
        tool = tool_registry.get("translate_text")
        assert tool is not None

    def test_archivist_rename_registered(self):
        """archivist_rename зарегистрирован."""
        from pds_ultimate.core.business_tools import register_all_tools
        from pds_ultimate.core.tools import tool_registry

        tool_registry._tools.clear()
        register_all_tools()
        tool = tool_registry.get("archivist_rename")
        assert tool is not None

    def test_google_calendar_registered(self):
        """google_calendar зарегистрирован."""
        from pds_ultimate.core.business_tools import register_all_tools
        from pds_ultimate.core.tools import tool_registry

        tool_registry._tools.clear()
        register_all_tools()
        tool = tool_registry.get("google_calendar")
        assert tool is not None
        assert tool.category == "calendar"


class TestToolExchangeRates:
    """Тесты tool handler exchange_rates."""

    @pytest.mark.asyncio
    async def test_exchange_rates_fixed_cny(self):
        """tool_exchange_rates: CNY."""
        from pds_ultimate.core.business_tools import tool_exchange_rates

        result = await tool_exchange_rates(
            from_currency="USD", to_currency="CNY", amount=100,
        )
        assert result.success is True
        assert "710" in result.output or "7.1" in result.output

    @pytest.mark.asyncio
    async def test_exchange_rates_fixed_tmt(self):
        """tool_exchange_rates: TMT."""
        from pds_ultimate.core.business_tools import tool_exchange_rates

        result = await tool_exchange_rates(
            from_currency="USD", to_currency="TMT", amount=10,
        )
        assert result.success is True
        assert "195" in result.output or "19.5" in result.output

    @pytest.mark.asyncio
    async def test_exchange_rates_all(self):
        """tool_exchange_rates: все курсы."""
        from pds_ultimate.core.business_tools import tool_exchange_rates

        result = await tool_exchange_rates()
        assert result is not None


class TestToolConvertFile:
    """Тесты tool handler convert_file."""

    @pytest.mark.asyncio
    async def test_convert_nonexistent(self):
        """tool_convert_file: несуществующий файл."""
        from pds_ultimate.core.business_tools import tool_convert_file

        result = await tool_convert_file(
            file_path="/nonexistent/file.xlsx",
            target_format="csv",
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_convert_json_to_csv(self):
        """tool_convert_file: json → csv."""
        import json
        import os
        import tempfile

        from pds_ultimate.core.business_tools import tool_convert_file

        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        ) as f:
            json.dump([{"a": 1, "b": 2}], f)
            path = f.name

        try:
            result = await tool_convert_file(
                file_path=path, target_format="csv",
            )
            assert result.success is True
            assert "✅" in result.output
        finally:
            os.unlink(path)
            # Cleanup target
            target = path.replace(".json", ".csv")
            if os.path.exists(target):
                os.unlink(target)


class TestToolTranslateText:
    """Тесты tool handler translate_text."""

    @pytest.mark.asyncio
    async def test_translate_text_mock(self):
        """tool_translate_text: с мок LLM."""
        from pds_ultimate.core.business_tools import tool_translate_text

        with patch(
            "pds_ultimate.modules.executive.translator.TranslatorService.translate"
        ) as mock:
            from pds_ultimate.modules.executive.translator import TranslationResult

            mock.return_value = TranslationResult(
                original="Hello",
                translated="Привет",
                source_lang="en",
                target_lang="ru",
            )
            result = await tool_translate_text(
                text="Hello", target_lang="ru",
            )
            assert result.success is True
            assert "Привет" in result.output


class TestToolArchivistRename:
    """Тесты tool handler archivist_rename."""

    @pytest.mark.asyncio
    async def test_archivist_nonexistent(self):
        """tool_archivist_rename: несуществующий файл."""
        from pds_ultimate.core.business_tools import tool_archivist_rename

        result = await tool_archivist_rename(
            file_path="/nonexistent/file.pdf",
        )
        assert result.success is False


class TestToolGoogleCalendar:
    """Тесты tool handler google_calendar."""

    @pytest.mark.asyncio
    async def test_calendar_today(self):
        """tool_google_calendar_events: today."""
        from pds_ultimate.core.business_tools import tool_google_calendar_events

        with patch(
            "pds_ultimate.integrations.google_calendar.GoogleCalendarService.get_today_events"
        ) as mock:
            mock.return_value = []
            result = await tool_google_calendar_events(action="today")
            assert result.success is True

    @pytest.mark.asyncio
    async def test_calendar_create_no_title(self):
        """tool_google_calendar_events: create без title."""
        from pds_ultimate.core.business_tools import tool_google_calendar_events

        result = await tool_google_calendar_events(action="create")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_calendar_unknown_action(self):
        """tool_google_calendar_events: неизвестный action."""
        from pds_ultimate.core.business_tools import tool_google_calendar_events

        result = await tool_google_calendar_events(action="xyz")
        assert result.success is False
