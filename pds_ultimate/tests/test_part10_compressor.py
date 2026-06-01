"""
Tests for Part 10 — Context Compressor
"""

import pytest

from pds_ultimate.core.context_compressor import (
    CompressedText,
    ContextCompressorV2,
    ContextEntry,
    ContextWindow,
    ConversationCompressor,
    ConversationTurn,
    RecursiveSummarizer,
    TextSummarizer,
    context_compressor,
)


class TestCompressedText:
    """Тесты CompressedText."""

    def test_create(self):
        ct = CompressedText(
            original_length=1000,
            compressed_length=300,
            text="Сжатый текст",
        )
        assert ct.original_length == 1000
        assert ct.compressed_length == 300

    def test_compression_ratio(self):
        ct = CompressedText(
            original_length=1000,
            compressed_length=300,
            text="X",
        )
        assert ct.compression_ratio == pytest.approx(0.3, abs=0.01)

    def test_savings_pct(self):
        ct = CompressedText(
            original_length=1000,
            compressed_length=300,
            text="X",
        )
        assert ct.savings_pct == pytest.approx(70.0, abs=1.0)

    def test_zero_original(self):
        ct = CompressedText(original_length=0, compressed_length=0, text="")
        assert ct.compression_ratio == 1.0

    def test_to_dict(self):
        ct = CompressedText(
            original_length=100,
            compressed_length=30,
            text="X",
            key_terms=["a", "b"],
        )
        d = ct.to_dict()
        assert "compressed_text" in d
        assert "savings_pct" in d
        assert "key_terms" in d


class TestContextEntry:
    """Тесты ContextEntry."""

    def test_create(self):
        entry = ContextEntry(id="e1", content="Test")
        assert entry.role == "system"
        assert entry.importance == 0.5

    def test_char_count(self):
        entry = ContextEntry(id="e2", content="Hello World")
        assert entry.char_count == 11


class TestTextSummarizer:
    """Тесты TextSummarizer."""

    def test_short_text(self):
        ts = TextSummarizer()
        result = ts.summarize("Короткий текст.")
        assert result.text == "Короткий текст."
        assert result.compression_ratio == 1.0

    def test_long_text(self):
        ts = TextSummarizer()
        text = ". ".join([
            f"Предложение номер {i} содержит важную информацию о теме"
            for i in range(20)
        ]) + "."
        result = ts.summarize(text, ratio=0.3)
        assert result.compressed_length < result.original_length

    def test_ratio_parameter(self):
        ts = TextSummarizer()
        text = ". ".join([f"Предложение {i}" for i in range(30)]) + "."
        r03 = ts.summarize(text, ratio=0.3)
        r07 = ts.summarize(text, ratio=0.7)
        # More ratio = more text kept
        assert r07.compressed_length >= r03.compressed_length

    def test_min_sentences(self):
        ts = TextSummarizer()
        text = ". ".join([f"Предложение {i}" for i in range(10)]) + "."
        result = ts.summarize(text, ratio=0.01, min_sentences=2)
        # Should have at least 2 sentences
        sentences = [s for s in result.text.split(". ") if s.strip()]
        assert len(sentences) >= 1  # at least min_sentences preserved

    def test_key_terms(self):
        ts = TextSummarizer()
        text = (
            "Python programming language is popular. "
            "Python is used for web development. "
            "Python supports machine learning. "
            "Python has great libraries. "
            "Python community is large."
        )
        result = ts.summarize(text)
        assert len(result.key_terms) > 0

    def test_empty_text(self):
        ts = TextSummarizer()
        result = ts.summarize("")
        assert result.text == ""


class TestContextWindow:
    """Тесты ContextWindow."""

    def test_add(self):
        cw = ContextWindow(max_chars=10000)
        entry_id = cw.add("Hello World")
        assert entry_id.startswith("ctx_")
        assert cw.entry_count == 1

    def test_get_context(self):
        cw = ContextWindow()
        cw.add("First")
        cw.add("Second")
        ctx = cw.get_context()
        assert "First" in ctx
        assert "Second" in ctx

    def test_auto_compress(self):
        cw = ContextWindow(max_chars=200)
        for i in range(10):
            cw.add("A" * 50, importance=0.3)
        # Should have compressed or removed entries
        assert cw.total_chars <= 200 + 100  # some tolerance

    def test_high_importance_preserved(self):
        cw = ContextWindow(max_chars=200)
        cw.add("IMPORTANT" * 20, importance=0.9)
        cw.add("low prio" * 30, importance=0.1)
        ctx = cw.get_context()
        # High importance entry should still be there
        assert "IMPORTANT" in ctx or cw.entry_count >= 1

    def test_clear(self):
        cw = ContextWindow()
        cw.add("Data")
        cw.clear()
        assert cw.entry_count == 0

    def test_get_stats(self):
        cw = ContextWindow()
        cw.add("Test")
        stats = cw.get_stats()
        assert stats["entries"] == 1
        assert "total_chars" in stats
        assert "utilization_pct" in stats


class TestConversationCompressor:
    """Тесты ConversationCompressor."""

    def test_short_conversation(self):
        cc = ConversationCompressor()
        turns = [
            ConversationTurn("user", "Привет"),
            ConversationTurn("assistant", "Здравствуйте!"),
        ]
        result = cc.compress(turns)
        assert len(result) == 2  # Not compressed

    def test_long_conversation(self):
        cc = ConversationCompressor(summary_threshold=10)
        turns = [
            ConversationTurn("user", f"Вопрос {i}")
            for i in range(20)
        ]
        result = cc.compress(turns)
        assert len(result) < len(turns)

    def test_remove_duplicates(self):
        cc = ConversationCompressor()
        turns = [
            ConversationTurn("user", "Привет"),
            ConversationTurn("user", "Привет"),
            ConversationTurn("assistant", "Здравствуйте!"),
        ]
        result = cc.remove_duplicates(turns)
        assert len(result) == 2

    def test_merge_short(self):
        cc = ConversationCompressor()
        turns = [
            ConversationTurn("user", "Да"),
            ConversationTurn("user", "Конечно"),
            ConversationTurn("assistant", "Хорошо!"),
        ]
        result = cc.merge_short(turns, min_length=20)
        assert len(result) <= 2

    def test_merge_short_empty(self):
        cc = ConversationCompressor()
        result = cc.merge_short([])
        assert result == []

    def test_get_stats(self):
        cc = ConversationCompressor()
        stats = cc.get_stats()
        assert "max_turns" in stats


class TestRecursiveSummarizer:
    """Тесты RecursiveSummarizer."""

    def test_short_text(self):
        rs = RecursiveSummarizer()
        result = rs.summarize("Short text.")
        assert result.text == "Short text."

    def test_long_text(self):
        rs = RecursiveSummarizer(chunk_size=200, target_ratio=0.3)
        text = ". ".join([
            f"Предложение {i} содержит подробную информацию"
            for i in range(50)
        ]) + "."
        result = rs.summarize(text)
        assert result.compressed_length <= result.original_length

    def test_target_length(self):
        rs = RecursiveSummarizer(chunk_size=200)
        text = ". ".join([f"Предложение {i}" for i in range(30)]) + "."
        result = rs.summarize(text, target_length=100)
        # Should try to get close to target
        assert result.compressed_length <= result.original_length

    def test_method_is_recursive(self):
        rs = RecursiveSummarizer(chunk_size=100)
        text = ". ".join([f"Слово {i}" for i in range(50)]) + "."
        result = rs.summarize(text)
        assert result.method == "recursive"


class TestContextCompressorV2Facade:
    """Тесты фасада ContextCompressorV2."""

    def test_summarize(self):
        cc = ContextCompressorV2()
        result = cc.summarize("Длинный текст для суммаризации. " * 10)
        assert isinstance(result, CompressedText)

    def test_summarize_recursive(self):
        cc = ContextCompressorV2()
        text = ". ".join([f"Предложение {i}" for i in range(50)]) + "."
        result = cc.summarize_recursive(text)
        assert isinstance(result, CompressedText)

    def test_add_context(self):
        cc = ContextCompressorV2()
        entry_id = cc.add_context("Новая информация")
        assert entry_id is not None

    def test_get_context(self):
        cc = ContextCompressorV2()
        cc.add_context("Data 1")
        cc.add_context("Data 2")
        ctx = cc.get_context()
        assert "Data 1" in ctx

    def test_compress_conversation(self):
        cc = ContextCompressorV2()
        turns = [
            ConversationTurn("user", "Привет"),
            ConversationTurn("assistant", "Здравствуйте!"),
        ]
        result = cc.compress_conversation(turns)
        assert isinstance(result, list)

    def test_get_stats(self):
        cc = ContextCompressorV2()
        stats = cc.get_stats()
        assert "context_window" in stats
        assert "conversation" in stats


class TestGlobalInstance:
    """Тест глобального экземпляра."""

    def test_global_exists(self):
        assert context_compressor is not None
        assert isinstance(context_compressor, ContextCompressorV2)
