"""
Тесты для Semantic Embeddings Engine.
========================================
Покрывает: EmbeddingModel, VectorIndex, SemanticSearchEngine.
"""


from pds_ultimate.core.semantic_engine import (
    EmbeddingModel,
    EmbeddingVector,
    SearchResult,
    SemanticSearchEngine,
    VectorIndex,
    semantic_engine,
)

# ═══════════════════════════════════════════════════════════════════════════════
# EMBEDDING VECTOR
# ═══════════════════════════════════════════════════════════════════════════════


class TestEmbeddingVector:
    def test_compute_norm(self):
        v = EmbeddingVector(doc_id="d1", vector={"a": 3.0, "b": 4.0})
        norm = v.compute_norm()
        assert abs(norm - 5.0) < 0.01

    def test_zero_norm(self):
        v = EmbeddingVector(doc_id="d1", vector={})
        assert v.compute_norm() == 0.0


class TestSearchResult:
    def test_to_dict(self):
        r = SearchResult(doc_id="d1", score=0.85, content="hello world")
        d = r.to_dict()
        assert d["doc_id"] == "d1"
        assert d["score"] == 0.85
        assert "hello" in d["content"]

    def test_long_content_truncated(self):
        r = SearchResult(doc_id="d1", score=0.5, content="x" * 500)
        d = r.to_dict()
        assert len(d["content"]) <= 200


# ═══════════════════════════════════════════════════════════════════════════════
# EMBEDDING MODEL
# ═══════════════════════════════════════════════════════════════════════════════


class TestEmbeddingModel:
    def setup_method(self):
        self.model = EmbeddingModel()

    def test_tokenize_russian(self):
        tokens = self.model.tokenize("Привет мир, как дела?")
        assert "привет" in tokens
        assert "мир" in tokens
        # stop words filtered
        assert "как" not in tokens

    def test_tokenize_english(self):
        tokens = self.model.tokenize("Hello world, this is a test")
        assert "hello" in tokens
        assert "world" in tokens
        assert "test" in tokens
        assert "this" not in tokens  # stop word

    def test_tokenize_empty(self):
        assert self.model.tokenize("") == []

    def test_char_trigrams(self):
        trigrams = self.model.char_trigrams("abc")
        assert "#ab" in trigrams
        assert "abc" in trigrams
        assert "bc#" in trigrams

    def test_word_bigrams(self):
        bigrams = self.model.word_bigrams(["hello", "world", "test"])
        assert "hello_world" in bigrams
        assert "world_test" in bigrams
        assert len(bigrams) == 2

    def test_word_bigrams_single(self):
        assert self.model.word_bigrams(["hello"]) == []

    def test_fit(self):
        docs = ["Python программирование", "Рецепт борща", "Python скрипт"]
        self.model.fit(docs)
        assert self.model._total_docs == 3
        assert len(self.model._idf) > 0

    def test_embed_basic(self):
        emb = self.model.embed("Python программирование")
        assert isinstance(emb, EmbeddingVector)
        assert len(emb.vector) > 0
        assert emb.norm > 0

    def test_embed_with_tags(self):
        emb = self.model.embed("Текст", tags=["python", "code"])
        assert "t:python" in emb.vector
        assert "t:code" in emb.vector

    def test_embed_empty(self):
        emb = self.model.embed("")
        assert emb.norm == 0.0

    def test_cosine_similarity_identical(self):
        emb1 = self.model.embed("Python программирование")
        emb2 = self.model.embed("Python программирование")
        sim = self.model.cosine_similarity(emb1, emb2)
        assert sim > 0.99

    def test_cosine_similarity_different(self):
        self.model.fit([
            "Python программирование код",
            "Рецепт борща свекла",
        ])
        emb1 = self.model.embed("Python программирование код")
        emb2 = self.model.embed("Рецепт борща свекла")
        sim = self.model.cosine_similarity(emb1, emb2)
        assert sim < 0.5

    def test_cosine_similarity_similar(self):
        self.model.fit([
            "Python программирование",
            "программирование на Python",
            "рецепт борща",
        ])
        emb1 = self.model.embed("Python программирование")
        emb2 = self.model.embed("программирование на Python")
        sim = self.model.cosine_similarity(emb1, emb2)
        assert sim > 0.3  # Should be similar

    def test_cosine_zero_norm(self):
        emb1 = EmbeddingVector(doc_id="d1", vector={}, norm=0.0)
        emb2 = self.model.embed("test")
        assert self.model.cosine_similarity(emb1, emb2) == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# VECTOR INDEX
# ═══════════════════════════════════════════════════════════════════════════════


class TestVectorIndex:
    def setup_method(self):
        self.model = EmbeddingModel()
        self.index = VectorIndex(self.model)

    def test_add(self):
        emb = self.index.add("doc1", "Hello world")
        assert self.index.size == 1
        assert isinstance(emb, EmbeddingVector)

    def test_add_multiple(self):
        self.index.add("d1", "Text one")
        self.index.add("d2", "Text two")
        assert self.index.size == 2

    def test_remove(self):
        self.index.add("d1", "Text one")
        assert self.index.remove("d1") is True
        assert self.index.size == 0

    def test_remove_missing(self):
        assert self.index.remove("nonexistent") is False

    def test_search_basic(self):
        self.index.add("d1", "Python программирование")
        self.index.add("d2", "Рецепт борща")
        results = self.index.search("Python код")
        assert len(results) >= 1
        assert results[0].doc_id == "d1"

    def test_search_empty_index(self):
        results = self.index.search("anything")
        assert results == []

    def test_search_with_tags(self):
        self.index.add("d1", "Текст", tags=["python"])
        self.index.add("d2", "Другой текст", tags=["cooking"])
        results = self.index.search("python", tags=["python"])
        found_ids = [r.doc_id for r in results]
        assert "d1" in found_ids

    def test_search_top_k(self):
        for i in range(20):
            self.index.add(f"d{i}", f"Document number {i} text")
        results = self.index.search("document text", top_k=5)
        assert len(results) <= 5

    def test_vocab_size(self):
        self.index.add("d1", "Hello world test")
        assert self.index.vocab_size > 0

    def test_clear(self):
        self.index.add("d1", "text")
        self.index.clear()
        assert self.index.size == 0
        assert self.index.vocab_size == 0

    def test_metadata_preserved(self):
        self.index.add("d1", "text", metadata={"type": "note"})
        results = self.index.search("text")
        if results:
            assert results[0].metadata.get("type") == "note"


# ═══════════════════════════════════════════════════════════════════════════════
# SEMANTIC SEARCH ENGINE
# ═══════════════════════════════════════════════════════════════════════════════


class TestSemanticSearchEngine:
    def setup_method(self):
        self.engine = SemanticSearchEngine()

    def test_add_document(self):
        doc_id = self.engine.add_document(text="Python is great")
        assert doc_id is not None
        assert self.engine.index.size == 1

    def test_add_document_custom_id(self):
        doc_id = self.engine.add_document(doc_id="my_doc", text="Hello")
        assert doc_id == "my_doc"

    def test_add_document_auto_id(self):
        id1 = self.engine.add_document(text="First")
        id2 = self.engine.add_document(text="Second")
        assert id1 != id2

    def test_remove_document(self):
        self.engine.add_document(doc_id="d1", text="Hello")
        assert self.engine.remove_document("d1") is True
        assert self.engine.index.size == 0

    def test_remove_missing(self):
        assert self.engine.remove_document("nonexistent") is False

    def test_search(self):
        self.engine.add_document(
            doc_id="py", text="Python программирование разработка")
        self.engine.add_document(
            doc_id="cook", text="Рецепт борща свекла морковь")
        results = self.engine.search("Python код")
        assert len(results) >= 1
        assert results[0].doc_id == "py"

    def test_search_empty(self):
        results = self.engine.search("anything")
        assert results == []

    def test_search_with_tags(self):
        self.engine.add_document(
            doc_id="d1", text="Data analysis",
            tags=["data", "python"]
        )
        results = self.engine.search("data", tags=["python"])
        assert len(results) >= 1

    def test_rebuild_index(self):
        self.engine.add_document(doc_id="d1", text="Python code")
        self.engine.add_document(doc_id="d2", text="Java code")
        self.engine.rebuild_index()
        # After rebuild, search should still work
        results = self.engine.search("Python")
        assert len(results) >= 1

    def test_get_stats(self):
        self.engine.add_document(text="test")
        self.engine.search("test")
        stats = self.engine.get_stats()
        assert stats["total_docs"] == 1
        assert stats["total_searches"] == 1
        assert "avg_search_ms" in stats

    def test_search_relevance_ordering(self):
        """More relevant results should rank higher."""
        self.engine.add_document(
            doc_id="exact", text="Python программирование машинное обучение")
        self.engine.add_document(
            doc_id="partial", text="программирование Java")
        self.engine.add_document(
            doc_id="unrelated", text="Рецепт борща свекла")
        self.engine.rebuild_index()

        results = self.engine.search("Python программирование")
        if len(results) >= 2:
            # exact match should be first
            assert results[0].doc_id == "exact"

    def test_properties(self):
        assert isinstance(self.engine.model, EmbeddingModel)
        assert isinstance(self.engine.index, VectorIndex)

    def test_many_documents(self):
        for i in range(50):
            self.engine.add_document(
                doc_id=f"d{i}",
                text=f"Document {i} about topic {i % 5}",
            )
        self.engine.rebuild_index()
        results = self.engine.search("document topic")
        assert len(results) > 0

    def test_min_score_filtering(self):
        self.engine.add_document(doc_id="d1", text="Python code")
        results = self.engine.search("completely unrelated xyz", min_score=0.9)
        assert len(results) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCE
# ═══════════════════════════════════════════════════════════════════════════════


class TestGlobalSemanticEngine:
    def test_exists(self):
        assert semantic_engine is not None
        assert isinstance(semantic_engine, SemanticSearchEngine)
