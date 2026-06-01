"""Tests for PDS-Ultimate v2 agent core."""

from __future__ import annotations

import pytest


class TestBM25:
    def test_search_relevance(self):
        from pds_ultimate.core.memory.bm25 import BM25Index

        idx = BM25Index()
        idx.add("1", "заказ логистика трек номер доставка")
        idx.add("2", "погода в ашхабаде солнечно")
        hits = idx.search("трек номер заказ", limit=2)
        assert hits[0][0] == "1"

    def test_empty_query(self):
        from pds_ultimate.core.memory.bm25 import BM25Index

        idx = BM25Index()
        idx.add("1", "test")
        assert idx.search("", limit=5) == []


class TestCompressor:
    def test_zero_llm_compression(self):
        from pds_ultimate.core.memory.compressor import compress_zero_llm

        obs = compress_zero_llm("user", "Запомни: мой склад в Берлине https://example.com")
        assert obs.narrative
        assert obs.importance > 0

    def test_facts_extracted(self):
        from pds_ultimate.core.memory.compressor import compress_zero_llm

        obs = compress_zero_llm("user", "Важно: оплатить счёт 1500 USD")
        assert len(obs.facts) >= 1


class TestTokenBudget:
    def test_trim_to_budget(self):
        from pds_ultimate.core.memory.token_budget import estimate_tokens, trim_to_budget

        items = ["x" * 400 for _ in range(10)]
        out = trim_to_budget(items, budget_tokens=50)
        assert estimate_tokens(out) <= 50


class TestMemoryStore:
    def test_remember_and_recall(self, tmp_path, monkeypatch):
        from pds_ultimate.core.memory.store import MemoryStore

        db = tmp_path / "test.db"
        monkeypatch.setattr("pds_ultimate.core.memory.store.DATABASE_PATH", db)
        store = MemoryStore()
        uid = 1129704360
        store.remember(uid, "Люблю кофе по утрам", layer="semantic", importance=0.9)
        store.remember(uid, "Склад в Берлине", layer="semantic", importance=0.8)
        hits = store.recall(uid, "кофе", limit=3)
        assert any("кофе" in h["content"].lower() for h in hits)

    def test_format_context_respects_budget(self, tmp_path, monkeypatch):
        from pds_ultimate.core.memory.store import MemoryStore

        db = tmp_path / "test2.db"
        monkeypatch.setattr("pds_ultimate.core.memory.store.DATABASE_PATH", db)
        store = MemoryStore()
        uid = 1
        for i in range(20):
            store.remember(uid, f"Факт номер {i} " + "x" * 100, layer="semantic")
        ctx = store.format_context(uid, query="факт", limit=10, budget_tokens=100)
        from pds_ultimate.core.memory.token_budget import estimate_tokens

        assert estimate_tokens(ctx) <= 100


class TestTools:
    def test_builtin_tools_registered(self):
        from pds_ultimate.core.tools.builtin import register_builtin_tools
        from pds_ultimate.core.tools.registry import tool_registry

        register_builtin_tools()
        names = {t.name for t in tool_registry.list_tools()}
        assert "shell_execute" in names
        assert "remember" in names
        assert "web_search" in names

    @pytest.mark.asyncio
    async def test_list_dir_tool(self):
        from pds_ultimate.core.tools.builtin import register_builtin_tools
        from pds_ultimate.core.tools.registry import tool_registry

        register_builtin_tools()
        result = await tool_registry.execute("list_dir", {"path": "."})
        assert result.success


class TestAgent:
    def test_should_use_tools_heuristic(self):
        from pds_ultimate.core.agent.ethan import agent
        import asyncio

        assert asyncio.run(agent.should_use_tools("привет")) is False
        assert asyncio.run(agent.should_use_tools("найди файл config.py и исправь баг")) is True

    def test_clean_json_helper(self):
        from pds_ultimate.core.agent import _clean_json_from_response

        raw = '{"action": {"answer": "Готово"}}'
        assert _clean_json_from_response(raw) == "Готово"


class TestConfig:
    def test_config_loads(self):
        from pds_ultimate.config import config

        assert config.telegram.token
        assert config.deepseek.api_key
        assert config.memory.token_budget > 0
