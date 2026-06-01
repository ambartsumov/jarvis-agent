"""
Tests for Part 10 — Tool Registrations & Handlers
"""

import pytest

from pds_ultimate.core.business_tools import (
    tool_check_freshness,
    tool_confidence_check,
    tool_expand_query,
    tool_find_gaps,
    tool_knowledge_add,
    tool_knowledge_search,
    tool_summarize_text,
    tool_task_add,
    tool_task_queue,
    tool_time_decay,
)
from pds_ultimate.core.tools import ToolResult, tool_registry


class TestPart10ToolRegistration:
    """Тест регистрации Part 10 инструментов."""

    def test_total_tool_count(self):
        """Всего 64 инструмента (46 Part 1-9 + 10 Part 10 + 4 Part 11 + 4 Part 12)."""
        from pds_ultimate.core.business_tools import register_all_tools

        tool_registry._tools.clear()
        count = register_all_tools()
        assert count == 64, f"Ожидалось 64, получено {count}"

    def test_part10_tools_registered(self):
        """Все Part 10 tools зарегистрированы."""
        from pds_ultimate.core.business_tools import register_all_tools

        tool_registry._tools.clear()
        register_all_tools()

        part10_names = [
            "knowledge_add",
            "knowledge_search",
            "confidence_check",
            "expand_query",
            "find_gaps",
            "task_add",
            "task_queue",
            "summarize_text",
            "check_freshness",
            "time_decay",
        ]
        for name in part10_names:
            tool = tool_registry.get(name)
            assert tool is not None, f"Tool '{name}' not registered"


class TestKnowledgeHandlers:
    """Тесты обработчиков Knowledge Base."""

    @pytest.mark.asyncio
    async def test_knowledge_add(self):
        result = await tool_knowledge_add(
            content="Python — язык программирования",
            category="fact",
            source="test",
            tags="python,programming",
        )
        assert isinstance(result, ToolResult)
        assert result.success is True
        assert "добавлено" in result.output.lower()

    @pytest.mark.asyncio
    async def test_knowledge_search(self):
        # Add first
        await tool_knowledge_add(
            content="Тестовый поиск знаний",
            category="general",
        )
        result = await tool_knowledge_search(query="тестовый поиск")
        assert isinstance(result, ToolResult)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_knowledge_search_empty(self):
        from pds_ultimate.core.semantic_search_v2 import SemanticSearchV2

        ss = SemanticSearchV2()  # Fresh instance, empty
        result = await tool_knowledge_search(
            query="несуществующий запрос 12345",
        )
        assert result.success is True


class TestConfidenceHandler:
    """Тесты обработчика Confidence."""

    @pytest.mark.asyncio
    async def test_confidence_check(self):
        result = await tool_confidence_check(
            text="Курс доллара составляет 90 рублей",
            source_count=3,
            source_agreement=0.8,
        )
        assert result.success is True
        assert "Уверенность" in result.output

    @pytest.mark.asyncio
    async def test_confidence_check_low(self):
        result = await tool_confidence_check(
            text="Может быть, вероятно",
            source_count=0,
            source_agreement=0.1,
        )
        assert result.success is True


class TestQueryExpansionHandlers:
    """Тесты обработчиков Query Expansion."""

    @pytest.mark.asyncio
    async def test_expand_query_synonym(self):
        result = await tool_expand_query(
            query="цена товара",
            strategy="synonym",
        )
        assert result.success is True
        assert "Расширение" in result.output

    @pytest.mark.asyncio
    async def test_expand_query_contextual(self):
        result = await tool_expand_query(
            query="импорт",
            context="Китай поставщики",
            strategy="contextual",
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_find_gaps_missing(self):
        result = await tool_find_gaps(
            query="Сколько стоит?",
            answer="Не знаю",
            confidence=0.1,
        )
        assert result.success is True
        assert "пробел" in result.output.lower() or result.data.get("count", 0) > 0

    @pytest.mark.asyncio
    async def test_find_gaps_complete(self):
        result = await tool_find_gaps(
            query="Как дела?",
            answer="Всё отлично! Сегодня выполнили 5 задач, "
                   "выручка 15000 долларов. Все показатели в норме. "
                   "Прогресс идёт по плану и все KPI выполнены.",
            confidence=0.9,
        )
        assert result.success is True


class TestTaskHandlers:
    """Тесты обработчиков Task Prioritizer."""

    @pytest.mark.asyncio
    async def test_task_add(self):
        result = await tool_task_add(
            name="Test Task",
            priority="high",
            task_type="api",
        )
        assert result.success is True
        assert "добавлена" in result.output.lower()

    @pytest.mark.asyncio
    async def test_task_queue_list(self):
        result = await tool_task_queue(action="list")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_task_queue_plan(self):
        from pds_ultimate.core.task_prioritizer import TaskPrioritizer

        tp = TaskPrioritizer()
        tp.add_task(name="Plan A")
        tp.add_task(name="Plan B")
        result = await tool_task_queue(action="plan")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_task_queue_stats(self):
        result = await tool_task_queue(action="stats")
        assert result.success is True
        assert "Статистика" in result.output

    @pytest.mark.asyncio
    async def test_task_queue_next(self):
        result = await tool_task_queue(action="next")
        assert result.success is True


class TestSummarizeHandler:
    """Тесты обработчика суммаризации."""

    @pytest.mark.asyncio
    async def test_summarize_text(self):
        text = ". ".join([
            f"Предложение номер {i} содержит информацию"
            for i in range(15)
        ]) + "."
        result = await tool_summarize_text(text=text, ratio=0.3)
        assert result.success is True
        assert "Суммаризация" in result.output

    @pytest.mark.asyncio
    async def test_summarize_short_text(self):
        result = await tool_summarize_text(text="Короткий текст.")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_summarize_recursive(self):
        text = ". ".join([f"Слово {i}" for i in range(50)]) + "."
        result = await tool_summarize_text(
            text=text, recursive=True,
        )
        assert result.success is True


class TestTimeRelevanceHandlers:
    """Тесты обработчиков Time & Relevance."""

    @pytest.mark.asyncio
    async def test_check_freshness(self):
        result = await tool_check_freshness(
            text="По данным за 2020 год, курс составлял..."
        )
        assert result.success is True
        assert "Свежесть" in result.output

    @pytest.mark.asyncio
    async def test_check_freshness_no_dates(self):
        result = await tool_check_freshness(
            text="Просто текст без дат"
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_time_decay(self):
        result = await tool_time_decay(
            score=0.8,
            age_days=90,
            method="exponential",
        )
        assert result.success is True
        assert "затухание" in result.output.lower()
        assert result.data["adjusted"] < 0.8

    @pytest.mark.asyncio
    async def test_time_decay_linear(self):
        result = await tool_time_decay(
            score=1.0,
            age_days=180,
            method="linear",
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_time_decay_hyperbolic(self):
        result = await tool_time_decay(
            score=0.5,
            age_days=50,
            method="hyperbolic",
        )
        assert result.success is True
