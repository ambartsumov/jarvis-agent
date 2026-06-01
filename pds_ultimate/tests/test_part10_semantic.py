"""
Tests for Part 10 — Semantic Search V2
"""

import time

from pds_ultimate.core.semantic_search_v2 import (
    ContextualSearch,
    DocumentStore,
    EmbeddingPruner,
    FreshnessLevel,
    KnowledgeBase,
    KnowledgeCategory,
    KnowledgeItem,
    SearchQuery,
    SemanticCache,
    SemanticSearchV2,
    semantic_search_v2,
)


class TestKnowledgeItem:
    """Тесты KnowledgeItem."""

    def test_create(self):
        item = KnowledgeItem(
            content="Тест", category=KnowledgeCategory.FACT,
        )
        assert item.id  # Auto-generated
        assert item.category == KnowledgeCategory.FACT
        assert item.confidence == 0.8  # default in dataclass

    def test_freshness(self):
        item = KnowledgeItem(
            content="Тест", category=KnowledgeCategory.GENERAL,
        )
        assert item.freshness == FreshnessLevel.FRESH
        assert not item.is_expired

    def test_relevance_score(self):
        item = KnowledgeItem(
            content="Тест",
            category=KnowledgeCategory.ANSWER,
            confidence=0.9,
        )
        score = item.relevance_score
        assert 0.0 <= score <= 1.0

    def test_age_days(self):
        item = KnowledgeItem(
            content="Тест",
            category=KnowledgeCategory.GENERAL,
        )
        assert item.age_days < 0.01  # Только что создан


class TestKnowledgeBase:
    """Тесты KnowledgeBase."""

    def test_add_and_get(self):
        kb = KnowledgeBase()
        item = kb.add("Знание 1", category=KnowledgeCategory.FACT)
        assert kb.get(item.id) is not None
        assert kb.size == 1

    def test_remove(self):
        kb = KnowledgeBase()
        item = kb.add("Удали", category=KnowledgeCategory.GENERAL)
        assert kb.remove(item.id) is True
        assert kb.get(item.id) is None

    def test_find_by_category(self):
        kb = KnowledgeBase()
        kb.add("A", category=KnowledgeCategory.FACT)
        kb.add("B", category=KnowledgeCategory.SKILL)
        kb.add("C", category=KnowledgeCategory.FACT)
        facts = kb.find_by_category(KnowledgeCategory.FACT)
        assert len(facts) == 2

    def test_find_by_tags(self):
        kb = KnowledgeBase()
        item1 = kb.add("A", category=KnowledgeCategory.GENERAL,
                       tags=["python", "dev"])
        kb.add("B", category=KnowledgeCategory.GENERAL,
               tags=["java"])
        found = kb.find_by_tags(["python"])
        assert len(found) == 1
        assert found[0].id == item1.id

    def test_cleanup_expired(self):
        kb = KnowledgeBase()
        item = kb.add("Old knowledge", category=KnowledgeCategory.GENERAL,
                      expires_hours=0.001)  # Tiny expiry
        # Manually set expires_at to past
        kb._items[item.id].expires_at = time.time() - 10
        removed = kb.cleanup_expired()
        assert removed == 1

    def test_get_stats(self):
        kb = KnowledgeBase()
        kb.add("X", category=KnowledgeCategory.GENERAL)
        stats = kb.get_stats()
        assert stats["total"] == 1
        assert "by_category" in stats

    def test_max_items(self):
        kb = KnowledgeBase(max_items=3)
        for i in range(5):
            kb.add(f"Item {i}", category=KnowledgeCategory.GENERAL)
        assert kb.size <= 3


class TestSearchQuery:
    """Тесты SearchQuery."""

    def test_create(self):
        q = SearchQuery(text="тест")
        assert q.text == "тест"
        assert q.max_results == 10

    def test_with_filters(self):
        q = SearchQuery(
            text="тест",
            category=KnowledgeCategory.FACT,
            min_confidence=0.8,
        )
        assert q.category == KnowledgeCategory.FACT
        assert q.min_confidence == 0.8


class TestDocumentStore:
    """Тесты DocumentStore."""

    def test_add_document(self):
        ds = DocumentStore()
        count = ds.add_document("doc1", "Это длинный текст для тестирования.")
        assert count >= 1
        assert ds.document_count == 1

    def test_remove_document(self):
        ds = DocumentStore()
        ds.add_document("doc2", "Текст для удаления.")
        assert ds.remove_document("doc2") is True
        assert ds.document_count == 0

    def test_search(self):
        ds = DocumentStore()
        ds.add_document("doc3", "Python программирование разработка кода")
        results = ds.search("программирование")
        assert isinstance(results, list)

    def test_get_stats(self):
        ds = DocumentStore()
        ds.add_document("s1", "Тест документ.")
        stats = ds.get_stats()
        assert stats["documents"] == 1
        assert "chunks" in stats


class TestContextualSearch:
    """Тесты ContextualSearch."""

    def test_create(self):
        kb = KnowledgeBase()
        cs = ContextualSearch(kb)
        assert cs is not None

    def test_sync_from_kb(self):
        kb = KnowledgeBase()
        kb.add("Тестовое знание для индексации",
               category=KnowledgeCategory.FACT)
        cs = ContextualSearch(kb)
        synced = cs.sync_from_kb()
        assert synced >= 0

    def test_search(self):
        kb = KnowledgeBase()
        kb.add("Python язык программирования",
               category=KnowledgeCategory.FACT)
        cs = ContextualSearch(kb)
        cs.sync_from_kb()
        q = SearchQuery(text="программирование")
        results = cs.search(q)
        assert isinstance(results, list)


class TestEmbeddingPruner:
    """Тесты EmbeddingPruner."""

    def test_prune_expired(self):
        kb = KnowledgeBase()
        item = kb.add("Expired knowledge", category=KnowledgeCategory.GENERAL,
                      expires_hours=0.001)
        kb._items[item.id].expires_at = time.time() - 10
        pruner = EmbeddingPruner(kb)
        removed = pruner.prune_expired()
        assert removed == 1

    def test_prune_low_confidence(self):
        kb = KnowledgeBase()
        lc = kb.add("Low conf", category=KnowledgeCategory.GENERAL,
                    confidence=0.1)
        hc = kb.add("High conf", category=KnowledgeCategory.GENERAL,
                    confidence=0.9)
        pruner = EmbeddingPruner(kb)
        removed = pruner.prune_low_confidence(min_confidence=0.5)
        assert removed == 1
        assert kb.get(hc.id) is not None

    def test_prune_all(self):
        kb = KnowledgeBase()
        pruner = EmbeddingPruner(kb)
        result = pruner.prune_all()
        assert "expired" in result
        assert "low_confidence" in result

    def test_get_stats(self):
        kb = KnowledgeBase()
        pruner = EmbeddingPruner(kb)
        stats = pruner.get_stats()
        assert "total" in stats


class TestSemanticCache:
    """Тесты SemanticCache."""

    def test_put_and_get(self):
        cache = SemanticCache()
        cache.put("тестовый запрос", {"answer": "ответ"})
        result = cache.get("тестовый запрос")
        assert result is not None
        assert result["response"]["answer"] == "ответ"

    def test_miss(self):
        cache = SemanticCache()
        result = cache.get("несуществующий запрос")
        assert result is None

    def test_clear(self):
        cache = SemanticCache()
        cache.put("q1", "r1")
        cache.clear()
        assert cache.get("q1") is None

    def test_hit_rate(self):
        cache = SemanticCache()
        cache.put("q", "r")
        cache.get("q")  # hit
        cache.get("unknown")  # miss
        rate = cache.hit_rate
        assert 0.0 <= rate <= 1.0

    def test_get_stats(self):
        cache = SemanticCache()
        stats = cache.get_stats()
        assert "entries" in stats
        assert "hit_rate" in stats


class TestSemanticSearchV2Facade:
    """Тесты фасада SemanticSearchV2."""

    def test_add_knowledge(self):
        ss = SemanticSearchV2()
        item_id = ss.add_knowledge(
            content="Тестовое знание",
            category="fact",
            source="test",
            tags=["test"],
        )
        assert item_id is not None

    def test_search_knowledge(self):
        ss = SemanticSearchV2()
        ss.add_knowledge("Python — язык программирования", category="fact")
        results = ss.search_knowledge("программирование")
        assert isinstance(results, list)

    def test_add_document(self):
        ss = SemanticSearchV2()
        count = ss.add_document("d1", "Длинный текст для документа.")
        assert count >= 1

    def test_search_documents(self):
        ss = SemanticSearchV2()
        ss.add_document("d2", "Машинное обучение и нейросети")
        results = ss.search_documents("нейросети")
        assert isinstance(results, list)

    def test_prune(self):
        ss = SemanticSearchV2()
        result = ss.prune()
        assert isinstance(result, dict)

    def test_get_stats(self):
        ss = SemanticSearchV2()
        stats = ss.get_stats()
        assert "knowledge_base" in stats
        assert "document_store" in stats
        assert "cache" in stats


class TestGlobalInstance:
    """Тест глобального экземпляра."""

    def test_global_exists(self):
        assert semantic_search_v2 is not None
        assert isinstance(semantic_search_v2, SemanticSearchV2)
