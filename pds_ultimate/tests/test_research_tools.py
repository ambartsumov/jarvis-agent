"""
PDS-Ultimate Research Tools Tests
====================================
Тесты для research tools (research, deep_research, quick_search).
Все тесты мокают reasoning_engine для изоляции.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pds_ultimate.core.internet_reasoning import (
    Contradiction,
    ContradictionSeverity,
    ExtractedFact,
    SourceInfo,
    SourceReliability,
    SynthesizedAnswer,
)
from pds_ultimate.core.tools import ToolResult

# Патчим глобальный объект в модуле-источнике
_PATCH_REASONING = "pds_ultimate.core.internet_reasoning.reasoning_engine"


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def sample_source():
    return SourceInfo(
        url="https://reuters.com/article",
        domain="reuters.com",
        title="Reuters News",
        trust_score=0.88,
        reliability=SourceReliability.HIGH,
        freshness_score=0.9,
    )


@pytest.fixture
def sample_answer(sample_source):
    """Успешный SynthesizedAnswer."""
    fact = ExtractedFact(
        text="Python is a popular programming language",
        source=sample_source,
        confidence=0.9,
        keywords=["python", "popular"],
    )
    return SynthesizedAnswer(
        query="Python programming",
        summary="📋 Результаты: Python is popular",
        facts=[fact],
        sources=[sample_source],
        contradictions=[],
        confidence=0.85,
        sources_count=1,
    )


@pytest.fixture
def sample_answer_with_contradictions(sample_source):
    """SynthesizedAnswer с противоречиями."""
    src2 = SourceInfo(
        url="https://bbc.com/news", domain="bbc.com",
        title="BBC", trust_score=0.85,
        reliability=SourceReliability.HIGH, freshness_score=0.8,
    )
    fa = ExtractedFact(
        text="Price is $100", source=sample_source,
        confidence=0.8, category="price", keywords=["price"],
    )
    fb = ExtractedFact(
        text="Price is $200", source=src2,
        confidence=0.7, category="price", keywords=["price"],
    )
    c = Contradiction(
        fact_a=fa, fact_b=fb,
        severity=ContradictionSeverity.MODERATE,
        description="Числовое расхождение: 100 vs 200",
    )
    return SynthesizedAnswer(
        query="Product price",
        summary="📋 Результаты с противоречиями",
        facts=[fa, fb],
        sources=[sample_source, src2],
        contradictions=[c],
        confidence=0.55,
        sources_count=2,
    )


@pytest.fixture
def empty_answer():
    """Пустой SynthesizedAnswer."""
    return SynthesizedAnswer(
        query="nonexistent topic",
        summary="По запросу «nonexistent topic» не найдено информации.",
        facts=[], sources=[], contradictions=[],
        confidence=0.0, sources_count=0,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL REGISTRATION
# ═══════════════════════════════════════════════════════════════════════════════


class TestResearchToolRegistration:
    """Проверяем что research tools зарегистрированы."""

    def test_register_all_includes_research_tools(self):
        from pds_ultimate.core.tools import ToolRegistry

        registry = ToolRegistry()
        from pds_ultimate.core.business_tools import register_all_tools

        with patch("pds_ultimate.core.business_tools.tool_registry", registry):
            count = register_all_tools()
            assert count >= 24  # 16 + 5 browser + 3 research

            research_tools = registry.list_tools(category="research")
            assert len(research_tools) == 3

            names = {t.name for t in research_tools}
            assert "research" in names
            assert "deep_research" in names
            assert "quick_search" in names

    def test_research_tool_schema(self):
        from pds_ultimate.core.tools import ToolRegistry

        registry = ToolRegistry()
        from pds_ultimate.core.business_tools import register_all_tools

        with patch("pds_ultimate.core.business_tools.tool_registry", registry):
            register_all_tools()
            tool = registry.get("research")
            assert tool is not None
            assert tool.category == "research"

            schema = tool.to_json_schema()
            func = schema["function"]
            params = func["parameters"]["properties"]
            assert "query" in params
            assert "max_sources" in params
            assert "query" in func["parameters"]["required"]

    def test_deep_research_tool_schema(self):
        from pds_ultimate.core.tools import ToolRegistry

        registry = ToolRegistry()
        from pds_ultimate.core.business_tools import register_all_tools

        with patch("pds_ultimate.core.business_tools.tool_registry", registry):
            register_all_tools()
            tool = registry.get("deep_research")
            assert tool is not None

            schema = tool.to_json_schema()
            params = schema["function"]["parameters"]["properties"]
            assert "query" in params
            assert "max_sources" in params

    def test_quick_search_tool_schema(self):
        from pds_ultimate.core.tools import ToolRegistry

        registry = ToolRegistry()
        from pds_ultimate.core.business_tools import register_all_tools

        with patch("pds_ultimate.core.business_tools.tool_registry", registry):
            register_all_tools()
            tool = registry.get("quick_search")
            assert tool is not None

            schema = tool.to_json_schema()
            params = schema["function"]["parameters"]["properties"]
            assert "query" in params
            assert "query" in schema["function"]["parameters"]["required"]

    def test_total_tools_count(self):
        """56 инструментов: 46 Part 1-9 + 10 Part 10."""
        from pds_ultimate.core.tools import ToolRegistry

        registry = ToolRegistry()
        from pds_ultimate.core.business_tools import register_all_tools

        with patch("pds_ultimate.core.business_tools.tool_registry", registry):
            count = register_all_tools()
            assert count == 64
            # list_names() filters visible=False (security_emergency)
            assert len(registry.list_names()) == 63


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL: research
# ═══════════════════════════════════════════════════════════════════════════════


class TestToolResearch:
    @pytest.mark.asyncio
    async def test_research_success(self, sample_answer):
        from pds_ultimate.core.business_tools import tool_research

        mock_engine = MagicMock()
        mock_engine.research = AsyncMock(return_value=sample_answer)

        with patch(_PATCH_REASONING, mock_engine):
            result = await tool_research(query="Python programming")

        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.tool_name == "research"
        assert "Python" in result.output
        assert "85%" in result.output
        mock_engine.research.assert_called_once()

    @pytest.mark.asyncio
    async def test_research_with_contradictions(
        self, sample_answer_with_contradictions,
    ):
        from pds_ultimate.core.business_tools import tool_research

        mock_engine = MagicMock()
        mock_engine.research = AsyncMock(
            return_value=sample_answer_with_contradictions,
        )

        with patch(_PATCH_REASONING, mock_engine):
            result = await tool_research(query="Product price")

        assert result.success is True
        assert "Противоречий" in result.output
        assert result.data["contradictions_count"] == 1

    @pytest.mark.asyncio
    async def test_research_empty_results(self, empty_answer):
        from pds_ultimate.core.business_tools import tool_research

        mock_engine = MagicMock()
        mock_engine.research = AsyncMock(return_value=empty_answer)

        with patch(_PATCH_REASONING, mock_engine):
            result = await tool_research(query="nonexistent")

        assert result.success is True
        assert "не найдено" in result.output
        assert result.data["confidence"] == 0.0

    @pytest.mark.asyncio
    async def test_research_custom_max_sources(self, sample_answer):
        from pds_ultimate.core.business_tools import tool_research

        mock_engine = MagicMock()
        mock_engine.research = AsyncMock(return_value=sample_answer)

        with patch(_PATCH_REASONING, mock_engine):
            await tool_research(query="test", max_sources=3)

        call_kwargs = mock_engine.research.call_args
        assert call_kwargs.kwargs["max_sources"] == 3

    @pytest.mark.asyncio
    async def test_research_error(self):
        from pds_ultimate.core.business_tools import tool_research

        mock_engine = MagicMock()
        mock_engine.research = AsyncMock(
            side_effect=RuntimeError("Browser not started"),
        )

        with patch(_PATCH_REASONING, mock_engine):
            result = await tool_research(query="test")

        assert result.success is False
        assert "Ошибка" in result.error

    @pytest.mark.asyncio
    async def test_research_data_dict(self, sample_answer):
        from pds_ultimate.core.business_tools import tool_research

        mock_engine = MagicMock()
        mock_engine.research = AsyncMock(return_value=sample_answer)

        with patch(_PATCH_REASONING, mock_engine):
            result = await tool_research(query="Python")

        assert "query" in result.data
        assert "confidence" in result.data
        assert "sources_count" in result.data

    @pytest.mark.asyncio
    async def test_research_quality_in_output(self, sample_answer):
        from pds_ultimate.core.business_tools import tool_research

        mock_engine = MagicMock()
        mock_engine.research = AsyncMock(return_value=sample_answer)

        with patch(_PATCH_REASONING, mock_engine):
            result = await tool_research(query="Python")

        assert "Качество" in result.output


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL: deep_research
# ═══════════════════════════════════════════════════════════════════════════════


class TestToolDeepResearch:
    @pytest.mark.asyncio
    async def test_deep_research_success(self, sample_answer):
        from pds_ultimate.core.business_tools import tool_deep_research

        mock_engine = MagicMock()
        mock_engine.deep_research = AsyncMock(return_value=sample_answer)
        mock_engine.get_stats = MagicMock(return_value={
            "queries": 3, "pages": 5, "facts": 15,
            "contradictions": 0, "time_ms": 2500,
        })

        with patch(_PATCH_REASONING, mock_engine):
            result = await tool_deep_research(query="Complex topic")

        assert result.success is True
        assert result.tool_name == "deep_research"
        assert "Статистика" in result.output
        mock_engine.deep_research.assert_called_once()

    @pytest.mark.asyncio
    async def test_deep_research_custom_sources(self, sample_answer):
        from pds_ultimate.core.business_tools import tool_deep_research

        mock_engine = MagicMock()
        mock_engine.deep_research = AsyncMock(return_value=sample_answer)
        mock_engine.get_stats = MagicMock(return_value={
            "queries": 1, "pages": 1, "facts": 1,
            "contradictions": 0, "time_ms": 100,
        })

        with patch(_PATCH_REASONING, mock_engine):
            await tool_deep_research(query="test", max_sources=15)

        call_kwargs = mock_engine.deep_research.call_args
        assert call_kwargs.kwargs["max_sources"] == 15

    @pytest.mark.asyncio
    async def test_deep_research_error(self):
        from pds_ultimate.core.business_tools import tool_deep_research

        mock_engine = MagicMock()
        mock_engine.deep_research = AsyncMock(
            side_effect=Exception("Network error"),
        )

        with patch(_PATCH_REASONING, mock_engine):
            result = await tool_deep_research(query="test")

        assert result.success is False
        assert "Ошибка" in result.error

    @pytest.mark.asyncio
    async def test_deep_research_stats_in_output(self, sample_answer):
        from pds_ultimate.core.business_tools import tool_deep_research

        mock_engine = MagicMock()
        mock_engine.deep_research = AsyncMock(return_value=sample_answer)
        mock_engine.get_stats = MagicMock(return_value={
            "queries": 5, "pages": 8, "facts": 20,
            "contradictions": 2, "time_ms": 3000,
        })

        with patch(_PATCH_REASONING, mock_engine):
            result = await tool_deep_research(query="topic")

        assert "5 запросов" in result.output
        assert "8 стр" in result.output
        assert "3000мс" in result.output

    @pytest.mark.asyncio
    async def test_deep_research_with_contradictions(
        self, sample_answer_with_contradictions,
    ):
        from pds_ultimate.core.business_tools import tool_deep_research

        mock_engine = MagicMock()
        mock_engine.deep_research = AsyncMock(
            return_value=sample_answer_with_contradictions,
        )
        mock_engine.get_stats = MagicMock(return_value={
            "queries": 3, "pages": 5, "facts": 10,
            "contradictions": 1, "time_ms": 2000,
        })

        with patch(_PATCH_REASONING, mock_engine):
            result = await tool_deep_research(query="price check")

        assert result.success is True
        assert "Противоречий" in result.output

    @pytest.mark.asyncio
    async def test_deep_research_facts_count(self, sample_answer):
        from pds_ultimate.core.business_tools import tool_deep_research

        mock_engine = MagicMock()
        mock_engine.deep_research = AsyncMock(return_value=sample_answer)
        mock_engine.get_stats = MagicMock(return_value={
            "queries": 1, "pages": 1, "facts": 1,
            "contradictions": 0, "time_ms": 100,
        })

        with patch(_PATCH_REASONING, mock_engine):
            result = await tool_deep_research(query="test")

        assert "Фактов проанализировано" in result.output


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL: quick_search
# ═══════════════════════════════════════════════════════════════════════════════


class TestToolQuickSearch:
    @pytest.mark.asyncio
    async def test_quick_search_success(self, sample_answer):
        from pds_ultimate.core.business_tools import tool_quick_search

        mock_engine = MagicMock()
        mock_engine.quick_search = AsyncMock(return_value=sample_answer)

        with patch(_PATCH_REASONING, mock_engine):
            result = await tool_quick_search(query="Simple question")

        assert result.success is True
        assert result.tool_name == "quick_search"
        mock_engine.quick_search.assert_called_once_with(
            query="Simple question",
        )

    @pytest.mark.asyncio
    async def test_quick_search_empty(self, empty_answer):
        from pds_ultimate.core.business_tools import tool_quick_search

        mock_engine = MagicMock()
        mock_engine.quick_search = AsyncMock(return_value=empty_answer)

        with patch(_PATCH_REASONING, mock_engine):
            result = await tool_quick_search(query="nothing")

        assert result.success is True
        assert result.data["confidence"] == 0.0

    @pytest.mark.asyncio
    async def test_quick_search_error(self):
        from pds_ultimate.core.business_tools import tool_quick_search

        mock_engine = MagicMock()
        mock_engine.quick_search = AsyncMock(
            side_effect=Exception("Timeout"),
        )

        with patch(_PATCH_REASONING, mock_engine):
            result = await tool_quick_search(query="test")

        assert result.success is False
        assert "Ошибка" in result.error

    @pytest.mark.asyncio
    async def test_quick_search_confidence_in_output(self, sample_answer):
        from pds_ultimate.core.business_tools import tool_quick_search

        mock_engine = MagicMock()
        mock_engine.quick_search = AsyncMock(return_value=sample_answer)

        with patch(_PATCH_REASONING, mock_engine):
            result = await tool_quick_search(query="test")

        assert "Уверенность" in result.output
        assert "Источников" in result.output

    @pytest.mark.asyncio
    async def test_quick_search_data_dict(self, sample_answer):
        from pds_ultimate.core.business_tools import tool_quick_search

        mock_engine = MagicMock()
        mock_engine.quick_search = AsyncMock(return_value=sample_answer)

        with patch(_PATCH_REASONING, mock_engine):
            result = await tool_quick_search(query="test")

        assert isinstance(result.data, dict)
        assert "query" in result.data
        assert "summary" in result.data
