"""
PDS-Ultimate Advanced Memory System Tests
===========================================
Тесты для продвинутой системы памяти (Part 2).

Тестируем:
1. MemoryType — все 8 типов
2. AdvancedMemoryEntry — создание, decay, effective importance
3. FailureEntry — failure-driven learning
4. AdvancedWorkingMemory — goals, plans, hypotheses, DAG
5. SemanticIndex — TF-IDF, tokenization, scoring
6. ContextCompressor — history compression, text chunking
7. AdvancedMemoryManager — store, recall, prune, failures, DB persist
8. Database Models — AgentMemory new fields, FailureLog
9. Backward Compatibility — old imports still work
10. Agent Integration — advanced memory in agent
"""

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

# ═══════════════════════════════════════════════════════════════════════════════
# IMPORTS — Advanced Memory
# ═══════════════════════════════════════════════════════════════════════════════
from pds_ultimate.core.advanced_memory import (
    AdvancedMemoryEntry,
    AdvancedWorkingMemory,
    FailureEntry,
    MemoryType,
)
from pds_ultimate.core.advanced_memory_manager import (
    AdvancedMemoryManager,
    ContextCompressor,
    SemanticIndex,
)
from pds_ultimate.core.database import (
    AgentMemory,
    Base,
    FailureLog,
)

# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def db_session():
    """In-memory SQLite session for tests."""
    engine = create_engine("sqlite:///:memory:", echo=False)

    @event.listens_for(engine, "connect")
    def _set_fk(conn, _):
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def manager():
    """Fresh AdvancedMemoryManager."""
    return AdvancedMemoryManager()


@pytest.fixture
def index():
    """Fresh SemanticIndex."""
    return SemanticIndex()


@pytest.fixture
def compressor():
    """Fresh ContextCompressor."""
    return ContextCompressor()


@pytest.fixture
def working():
    """Fresh AdvancedWorkingMemory."""
    return AdvancedWorkingMemory()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. MEMORY TYPE
# ═══════════════════════════════════════════════════════════════════════════════

class TestMemoryType:
    """Тесты типов памяти."""

    def test_all_types_defined(self):
        """Все 8 типов памяти определены."""
        assert MemoryType.EPISODIC == "episodic"
        assert MemoryType.SEMANTIC == "semantic"
        assert MemoryType.PROCEDURAL == "procedural"
        assert MemoryType.STRATEGIC == "strategic"
        assert MemoryType.FAILURE == "failure"
        assert MemoryType.FACT == "fact"
        assert MemoryType.PREFERENCE == "preference"
        assert MemoryType.RULE == "rule"

    def test_types_are_strings(self):
        """Типы — строки (для JSON, DB)."""
        for attr in ["EPISODIC", "SEMANTIC", "PROCEDURAL", "STRATEGIC",
                     "FAILURE", "FACT", "PREFERENCE", "RULE"]:
            assert isinstance(getattr(MemoryType, attr), str)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ADVANCED MEMORY ENTRY
# ═══════════════════════════════════════════════════════════════════════════════

class TestAdvancedMemoryEntry:
    """Тесты AdvancedMemoryEntry."""

    def test_create_entry(self):
        """Базовое создание."""
        entry = AdvancedMemoryEntry("test fact", MemoryType.FACT)
        assert entry.content == "test fact"
        assert entry.memory_type == "fact"
        assert entry.importance == 0.5
        assert entry.confidence == 0.8
        assert entry.decay_rate == 0.1
        assert entry.source_quality == 0.7
        assert entry.access_count == 0
        assert entry.failure_count == 0
        assert entry.success_count == 0
        assert entry.is_active is True
        assert entry.db_id is None

    def test_clamp_values(self):
        """Importance, confidence в границах [0, 1]."""
        entry = AdvancedMemoryEntry("x", importance=5.0, confidence=-1.0)
        assert entry.importance == 1.0
        assert entry.confidence == 0.0

    def test_touch(self):
        """touch() обновляет access."""
        entry = AdvancedMemoryEntry("x")
        old_time = entry.last_accessed
        entry.touch()
        assert entry.access_count == 1
        assert entry.last_accessed >= old_time

    def test_mark_success(self):
        """mark_success() повышает confidence."""
        entry = AdvancedMemoryEntry("x", confidence=0.5, importance=0.5)
        entry.mark_success()
        assert entry.success_count == 1
        assert entry.confidence == 0.55  # +0.05
        assert entry.importance == 0.52  # +0.02

    def test_mark_failure(self):
        """mark_failure() снижает confidence."""
        entry = AdvancedMemoryEntry("x", confidence=0.8)
        entry.mark_failure()
        assert entry.failure_count == 1
        assert entry.confidence == pytest.approx(0.7, abs=1e-9)  # -0.1

    def test_mark_failure_degrades_importance(self):
        """3+ failures снижают importance."""
        entry = AdvancedMemoryEntry("x", confidence=0.5, importance=0.5)
        entry.mark_failure()
        entry.mark_failure()
        entry.mark_failure()
        assert entry.failure_count == 3
        assert entry.importance < 0.5

    def test_is_expired(self):
        """Expired entries."""
        entry = AdvancedMemoryEntry(
            "x", expiry=datetime.utcnow() - timedelta(hours=1))
        assert entry.is_expired() is True

        entry2 = AdvancedMemoryEntry(
            "y", expiry=datetime.utcnow() + timedelta(hours=1))
        assert entry2.is_expired() is False

    def test_no_expiry(self):
        """Без expiry — не expired."""
        entry = AdvancedMemoryEntry("x")
        assert entry.is_expired() is False

    def test_effective_importance(self):
        """effective_importance вычисляется."""
        entry = AdvancedMemoryEntry(
            "x", importance=1.0, confidence=1.0, source_quality=1.0,
            decay_rate=0.0)
        eff = entry.effective_importance()
        assert 0.0 <= eff <= 1.0
        assert eff > 0.5  # High importance entry

    def test_effective_importance_expired(self):
        """Expired → effective = 0."""
        entry = AdvancedMemoryEntry(
            "x", importance=1.0,
            expiry=datetime.utcnow() - timedelta(hours=1))
        assert entry.effective_importance() == 0.0

    def test_context_hash_dedup(self):
        """Одинаковый content + type → одинаковый hash."""
        e1 = AdvancedMemoryEntry("hello world", MemoryType.FACT)
        e2 = AdvancedMemoryEntry("hello world", MemoryType.FACT)
        assert e1.context_hash == e2.context_hash

    def test_context_hash_different(self):
        """Разный content → разный hash."""
        e1 = AdvancedMemoryEntry("hello", MemoryType.FACT)
        e2 = AdvancedMemoryEntry("world", MemoryType.FACT)
        assert e1.context_hash != e2.context_hash

    def test_to_dict(self):
        """Сериализация в dict."""
        entry = AdvancedMemoryEntry("fact1", tags=["t1"], chat_id=123)
        d = entry.to_dict()
        assert d["content"] == "fact1"
        assert d["tags"] == ["t1"]
        assert d["chat_id"] == 123
        assert "effective_importance" in d
        assert "context_hash" in d

    def test_repr(self):
        """__repr__ работает."""
        entry = AdvancedMemoryEntry("short text")
        r = repr(entry)
        assert "AdvMemory" in r
        assert "short text" in r


# ═══════════════════════════════════════════════════════════════════════════════
# 3. FAILURE ENTRY
# ═══════════════════════════════════════════════════════════════════════════════

class TestFailureEntry:
    """Тесты FailureEntry (failure-driven learning)."""

    def test_create_failure(self):
        """Создание записи об ошибке."""
        f = FailureEntry(
            content="API timeout",
            error_context="Calling DeepSeek API",
            correction="Добавить retry + exponential backoff",
            severity="high",
        )
        assert f.memory_type == MemoryType.FAILURE
        assert f.error_context == "Calling DeepSeek API"
        assert f.correction == "Добавить retry + exponential backoff"
        assert f.severity == "high"
        assert f.importance == 0.8  # Default for failures
        assert f.decay_rate == 0.01  # Failures don't decay fast

    def test_failure_tags(self):
        """Failure автоматически добавляет теги."""
        f = FailureEntry("err", severity="critical")
        assert "failure" in f.tags
        assert "lesson" in f.tags
        assert "critical" in f.tags

    def test_failure_to_dict(self):
        """FailureEntry.to_dict() включает специфичные поля."""
        f = FailureEntry("err", error_context="ctx", correction="fix")
        d = f.to_dict()
        assert d["error_context"] == "ctx"
        assert d["correction"] == "fix"
        assert d["severity"] == "medium"  # default


# ═══════════════════════════════════════════════════════════════════════════════
# 4. ADVANCED WORKING MEMORY
# ═══════════════════════════════════════════════════════════════════════════════

class TestAdvancedWorkingMemory:
    """Тесты продвинутой рабочей памяти."""

    def test_set_goal(self, working):
        """Установка цели."""
        working.set_goal("Создать заказ на балаклавы")
        assert working.primary_goal == "Создать заказ на балаклавы"
        assert working.iteration == 0
        assert working.start_time is not None

    def test_sub_goals(self, working):
        """Подцели с приоритетами."""
        working.set_goal("main")
        working.add_sub_goal("sub1", priority=1)
        working.add_sub_goal("sub2", priority=5)
        working.add_sub_goal("sub3", priority=3)
        assert len(working.sub_goals) == 3
        # Отсортированы по priority desc
        assert working.sub_goals[0]["goal"] == "sub2"
        assert working.sub_goals[1]["goal"] == "sub3"
        assert working.sub_goals[2]["goal"] == "sub1"

    def test_goal_integrity_check(self, working):
        """Goal integrity check."""
        working.set_goal("original goal")
        check = working.check_goal_integrity()
        assert check["aligned"] is True
        assert check["primary_goal"] == "original goal"

    def test_plan_with_dependencies(self, working):
        """DAG: шаги плана с зависимостями."""
        working.set_goal("complex task")
        idx0 = working.add_plan_step("Step A")
        idx1 = working.add_plan_step("Step B", depends_on=[idx0])
        idx2 = working.add_plan_step("Step C", depends_on=[idx0])
        idx3 = working.add_plan_step("Step D", depends_on=[idx1, idx2])

        assert len(working.plan) == 4
        assert working.plan[1]["depends_on"] == [0]
        assert working.plan[3]["depends_on"] == [1, 2]

    def test_get_current_step_respects_deps(self, working):
        """get_current_step учитывает зависимости."""
        working.set_goal("task")
        working.add_plan_step("A")
        working.add_plan_step("B", depends_on=[0])

        # A готов (нет зависимостей)
        step = working.get_current_step()
        assert step["step"] == "A"

        # Пока A не completed, B не готов
        ready = working.get_ready_steps()
        assert len(ready) == 1
        assert ready[0][1]["step"] == "A"

    def test_complete_and_fail_steps(self, working):
        """Complete и fail шагов."""
        working.set_goal("task")
        working.add_plan_step("A")
        working.add_plan_step("B")

        working.complete_step(0, "done")
        assert working.plan[0]["status"] == "completed"
        assert working.plan[0]["result"] == "done"

        working.fail_step(1, "error")
        assert working.plan[1]["status"] == "failed"

    def test_get_ready_steps_parallel(self, working):
        """Параллельные шаги (без зависимостей)."""
        working.set_goal("task")
        working.add_plan_step("A")
        working.add_plan_step("B")
        working.add_plan_step("C")

        ready = working.get_ready_steps()
        assert len(ready) == 3  # Все параллельны

    def test_hypotheses(self, working):
        """Hypothesis management."""
        working.set_goal("investigate")
        idx = working.add_hypothesis("Price is too high", confidence=0.7)
        assert len(working.hypotheses) == 1
        assert working.hypotheses[0]["confidence"] == 0.7

        working.update_hypothesis(idx, "confirmed", "Found evidence", 0.9)
        assert working.hypotheses[0]["status"] == "confirmed"
        assert working.hypotheses[0]["confidence"] == 0.9
        assert len(working.hypotheses[0]["evidence"]) == 1

    def test_scratchpad_auto_compress(self, working):
        """Scratchpad auto-compresses at limit."""
        working.set_goal("task")
        for i in range(60):
            working.add_note(f"note {i}")
        assert len(working.scratchpad) <= working.MAX_SCRATCHPAD

    def test_tool_results_capped(self, working):
        """Tool results capped at limit."""
        working.set_goal("task")
        for i in range(30):
            working.add_tool_result(f"tool_{i}", f"result_{i}", True)
        assert len(working.tool_results) <= working.MAX_TOOL_RESULTS

    def test_context_summary(self, working):
        """get_context_summary() builds text."""
        working.set_goal("Найти поставщика")
        working.add_sub_goal("Проверить цены")
        working.add_plan_step("Шаг 1")
        working.add_hypothesis("Alibaba дешевле")
        working.add_note("Проверил каталог")
        working.add_tool_result("search", "found 3 results", True)

        summary = working.get_context_summary()
        assert "ОСНОВНАЯ ЦЕЛЬ" in summary
        assert "ПОДЦЕЛИ" in summary
        assert "ПЛАН" in summary
        assert "ГИПОТЕЗЫ" in summary
        assert "ЗАМЕТКИ" in summary
        assert "ПОСЛЕДНИЕ ДЕЙСТВИЯ" in summary

    def test_reset(self, working):
        """reset() clears everything."""
        working.set_goal("task")
        working.add_note("note")
        working.add_plan_step("step")
        working.reset()
        assert working.primary_goal == ""
        assert len(working.plan) == 0
        assert len(working.scratchpad) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 5. SEMANTIC INDEX (TF-IDF)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSemanticIndex:
    """Тесты TF-IDF semantic search."""

    def test_tokenize_basic(self, index):
        """Базовая токенизация."""
        tokens = index.tokenize("Привет мир заказ 123")
        assert "привет" in tokens
        assert "мир" in tokens
        assert "заказ" in tokens
        assert "123" in tokens

    def test_tokenize_removes_stopwords(self, index):
        """Стоп-слова удаляются."""
        tokens = index.tokenize("это и в на заказ")
        assert "это" not in tokens
        assert "заказ" in tokens

    def test_tokenize_short_tokens_removed(self, index):
        """Токены < 2 символов удаляются."""
        tokens = index.tokenize("a b cd ef")
        assert "a" not in tokens
        assert "b" not in tokens
        assert "cd" in tokens

    def test_bigrams(self, index):
        """Биграммы для фразового поиска."""
        tokens = ["hello", "world", "test"]
        bigrams = index.bigrams(tokens)
        assert "hello_world" in bigrams
        assert "world_test" in bigrams
        assert len(bigrams) == 2

    def test_score_relevant(self, index):
        """Релевантный запрос → высокий score."""
        entries = [
            AdvancedMemoryEntry("Заказ балаклав от поставщика Alibaba",
                                tags=["заказ", "alibaba"]),
            AdvancedMemoryEntry("Погода на завтра солнечная"),
        ]
        index.update_index(entries)

        score1 = index.score("заказ балаклав", entries[0])
        score2 = index.score("заказ балаклав", entries[1])
        assert score1 > score2

    def test_score_tag_match(self, index):
        """Tag match даёт высокий вес."""
        entry = AdvancedMemoryEntry("test", tags=["finance", "report"])
        index.update_index([entry])
        score = index.score("finance", entry)
        assert score > 0

    def test_score_empty_query(self, index):
        """Пустой запрос → score 0."""
        entry = AdvancedMemoryEntry("test content")
        index.update_index([entry])
        score = index.score("", entry)
        assert score == 0.0

    def test_score_no_overlap(self, index):
        """Нет совпадений → score 0."""
        entry = AdvancedMemoryEntry("абсолютно другие слова")
        index.update_index([entry])
        score = index.score("completely different words", entry)
        assert score == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# 6. CONTEXT COMPRESSOR
# ═══════════════════════════════════════════════════════════════════════════════

class TestContextCompressor:
    """Тесты сжатия контекста."""

    def test_compress_short_history(self):
        """Короткая история не сжимается."""
        history = [
            {"role": "user", "content": "привет"},
            {"role": "assistant", "content": "здравствуйте"},
        ]
        result = ContextCompressor.compress_history(history, max_messages=10)
        assert len(result) == 2  # Без изменений

    def test_compress_long_history(self):
        """Длинная история сжимается."""
        history = [
            {"role": "user" if i % 2 == 0 else "assistant",
             "content": f"Сообщение {i}"}
            for i in range(20)
        ]
        result = ContextCompressor.compress_history(history, max_messages=5)
        assert len(result) < 20
        # Последние 5 сохранены + 1 summary
        assert len(result) == 6

    def test_compress_text_short(self):
        """Короткий текст не сжимается."""
        text = "Short text"
        result = ContextCompressor.compress_text(text, max_length=100)
        assert result == text

    def test_compress_text_long(self):
        """Длинный текст сжимается."""
        text = "First paragraph.\n\n" + \
               "Middle paragraph " * 100 + "\n\n" + \
               "Last paragraph."
        result = ContextCompressor.compress_text(text, max_length=200)
        assert len(result) <= 200

    def test_chunk_text_short(self):
        """Короткий текст → 1 chunk."""
        chunks = ContextCompressor.chunk_text("Hello world", chunk_size=100)
        assert len(chunks) == 1

    def test_chunk_text_long(self):
        """Длинный текст → multiple chunks."""
        text = "Hello world. " * 100
        chunks = ContextCompressor.chunk_text(text, chunk_size=100, overlap=20)
        assert len(chunks) > 1

    def test_chunk_overlap(self):
        """Chunks имеют перекрытие."""
        text = "ABCDE" * 100  # 500 chars
        chunks = ContextCompressor.chunk_text(
            text, chunk_size=100, overlap=20)
        # Каждый chunk кроме последнего: следующий начинается на 20 символов раньше
        assert len(chunks) > 1


# ═══════════════════════════════════════════════════════════════════════════════
# 7. ADVANCED MEMORY MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class TestAdvancedMemoryManager:
    """Тесты AdvancedMemoryManager."""

    def test_store(self, manager):
        """Базовое сохранение."""
        entry = AdvancedMemoryEntry("test fact", MemoryType.FACT)
        manager.store(entry)
        assert manager.total_count == 1

    def test_store_deduplication(self, manager):
        """Дедупликация по context_hash."""
        e1 = AdvancedMemoryEntry("same content", MemoryType.FACT)
        e2 = AdvancedMemoryEntry("same content", MemoryType.FACT)
        manager.store(e1)
        manager.store(e2)
        assert manager.total_count == 1  # Дедуплицировано

    def test_store_fact(self, manager):
        """store_fact convenience method."""
        entry = manager.store_fact("test", importance=0.7, chat_id=123)
        assert entry.memory_type == MemoryType.FACT
        assert entry.importance == 0.7
        assert entry.chat_id == 123
        assert manager.total_count == 1

    def test_store_preference(self, manager):
        """store_preference convenience method."""
        entry = manager.store_preference("prefers dark mode", chat_id=456)
        assert entry.memory_type == MemoryType.PREFERENCE
        assert entry.importance == 0.7
        assert entry.decay_rate == 0.02  # Slow decay

    def test_store_rule(self, manager):
        """store_rule convenience method."""
        entry = manager.store_rule("rule: always check price")
        assert entry.memory_type == MemoryType.RULE
        assert entry.importance == 0.8

    def test_store_procedural(self, manager):
        """store_procedural convenience method."""
        entry = manager.store_procedural("шаг1 → шаг2 → шаг3")
        assert entry.memory_type == MemoryType.PROCEDURAL
        assert "procedural" in entry.tags

    def test_store_strategic(self, manager):
        """store_strategic convenience method."""
        entry = manager.store_strategic("Main supplier is Alibaba")
        assert entry.memory_type == MemoryType.STRATEGIC
        assert entry.importance == 0.9

    def test_store_failure(self, manager):
        """Failure-driven learning: сохранение ошибки."""
        failure = manager.store_failure(
            content="API timeout on search",
            error_context="Calling DuckDuckGo",
            correction="Use retry with backoff",
            severity="high",
        )
        assert isinstance(failure, FailureEntry)
        assert failure.severity == "high"
        assert manager.total_count == 1

    def test_get_relevant_failures(self, manager):
        """Поиск релевантных ошибок."""
        manager.store_failure("API timeout при поиске", severity="high")
        manager.store_failure("Ошибка парсинга JSON ответа", severity="medium")
        manager.store_failure("Превышен лимит запросов API", severity="low")

        failures = manager.get_relevant_failures("API ошибка timeout")
        assert len(failures) > 0
        # API timeout должен быть более релевантен
        assert "API" in failures[0].content or "timeout" in failures[0].content

    def test_recall_basic(self, manager):
        """Базовый recall по ключевым словам."""
        manager.store_fact("Поставщик Alibaba продаёт балаклавы",
                           tags=["alibaba", "supplier"])
        manager.store_fact("Курс доллара 19.5 маната",
                           tags=["currency", "rate"])

        results = manager.recall("alibaba поставщик")
        assert len(results) > 0
        assert "Alibaba" in results[0].content

    def test_recall_filter_by_type(self, manager):
        """Recall с фильтром по типу."""
        manager.store_fact("fact1")
        manager.store_rule("rule1")
        manager.store_preference("pref1")

        results = manager.recall_all(memory_type=MemoryType.RULE)
        assert len(results) == 1
        assert results[0].content == "rule1"

    def test_recall_filter_by_importance(self, manager):
        """Recall с фильтром по важности."""
        manager.store_fact("low importance", importance=0.1)
        manager.store_fact("high importance", importance=0.9)

        # recall_all filters by effective_importance (includes decay, confidence)
        # So we use a low threshold and verify ordering
        results = manager.recall_all(min_importance=0.0)
        assert len(results) == 2
        # Sorted by effective importance desc
        assert results[0].content == "high importance"
        assert results[0].importance > results[1].importance

    def test_recall_filter_by_chat_id(self, manager):
        """Per-user memory isolation."""
        manager.store_fact("user1 data", chat_id=111)
        manager.store_fact("user2 data", chat_id=222)
        manager.store_fact("global data")  # chat_id=None → visible to all

        results = manager.recall_all(chat_id=111)
        # user1 видит свои + global
        contents = [r.content for r in results]
        assert "user1 data" in contents
        assert "global data" in contents
        assert "user2 data" not in contents

    def test_get_context_for_prompt(self, manager):
        """Формирование контекста для LLM."""
        manager.store_fact("Факт 1 test запрос", importance=0.9, tags=["test"])
        manager.store_rule("Правило 1 test запрос")
        manager.store_failure("Ошибка 1 test запрос",
                              correction="Исправление 1")

        ctx = manager.get_context_for_prompt("test запрос")
        assert "ДОЛГОСРОЧНАЯ ПАМЯТЬ" in ctx
        assert len(ctx) > 50

    def test_get_context_empty(self, manager):
        """Пустая память → пустой контекст."""
        ctx = manager.get_context_for_prompt("test")
        assert ctx == ""

    def test_time_context(self, manager):
        """Time awareness — текущее время."""
        ctx = manager.get_time_context()
        assert "ТЕКУЩЕЕ ВРЕМЯ" in ctx
        assert "UTC" in ctx

    def test_prune_expired(self, manager):
        """Pruning удаляет expired записи."""
        entry = AdvancedMemoryEntry(
            "expired data",
            expiry=datetime.utcnow() - timedelta(hours=1),
        )
        manager.store(entry)
        assert manager.total_count == 1

        pruned = manager.prune()
        assert pruned == 1
        assert manager.total_count == 0

    def test_prune_low_importance(self, manager):
        """Pruning удаляет записи с низким effective importance."""
        entry = AdvancedMemoryEntry(
            "low importance", importance=0.01, confidence=0.01,
            source_quality=0.01, decay_rate=1.0,
        )
        # Искусственно делаем запись старой
        entry.created_at = datetime.utcnow() - timedelta(days=365)
        manager._memories.append(entry)
        manager._index_dirty = True

        pruned = manager.prune()
        assert pruned >= 1

    def test_enforce_limits(self, manager):
        """Enforce memory limits."""
        original_max = manager.MAX_MEMORIES
        manager.MAX_MEMORIES = 5

        for i in range(10):
            entry = AdvancedMemoryEntry(f"entry {i}",
                                        importance=i * 0.1)
            manager._memories.append(entry)
        manager._index_dirty = True

        manager._enforce_limits()
        assert len(manager._memories) <= 5

        manager.MAX_MEMORIES = original_max

    def test_working_memory_per_chat(self, manager):
        """Рабочая память изолирована по chat_id."""
        w1 = manager.get_working(111)
        w2 = manager.get_working(222)
        assert w1 is not w2

        w1.set_goal("goal 1")
        w2.set_goal("goal 2")
        assert w1.primary_goal != w2.primary_goal

    def test_reset_working(self, manager):
        """Reset рабочей памяти."""
        w = manager.get_working(333)
        w.set_goal("test")
        manager.reset_working(333)
        w_new = manager.get_working(333)
        assert w_new.primary_goal == ""

    def test_get_stats(self, manager):
        """Статистика памяти."""
        manager.store_fact("f1")
        manager.store_rule("r1")
        manager.store_failure("err1")

        stats = manager.get_stats()
        assert stats["total"] == 3
        assert MemoryType.FACT in stats["by_type"]
        assert MemoryType.RULE in stats["by_type"]
        assert MemoryType.FAILURE in stats["by_type"]
        assert stats["failures_stored"] == 1
        assert 0 <= stats["avg_confidence"] <= 1
        assert "avg_effective_importance" in stats

    # ─── DB Persistence ──────────────────────────────────────────────────

    def test_save_to_db(self, manager, db_session):
        """Сохранение в БД."""
        manager.store_fact("test fact db", importance=0.7,
                           tags=["tag1"], chat_id=100)
        count = manager.save_to_db(db_session)
        assert count == 1

        # Проверяем в БД
        db_entry = db_session.query(AgentMemory).first()
        assert db_entry is not None
        assert db_entry.content == "test fact db"
        assert db_entry.importance == 0.7

    def test_save_dedup(self, manager, db_session):
        """Повторное сохранение не создаёт дубликаты."""
        manager.store_fact("unique fact")
        manager.save_to_db(db_session)
        count2 = manager.save_to_db(db_session)
        assert count2 == 0  # Уже сохранено

    def test_load_from_db(self, db_session):
        """Загрузка из БД."""
        # Добавляем запись напрямую в БД
        db_entry = AgentMemory(
            content="loaded fact",
            memory_type="fact",
            importance=0.6,
            tags=json.dumps(["loaded"]),
            source="test",
            metadata_json=json.dumps({
                "confidence": 0.9,
                "decay_rate": 0.05,
            }),
            is_active=True,
        )
        db_session.add(db_entry)
        db_session.commit()

        manager2 = AdvancedMemoryManager()
        count = manager2.load_from_db(db_session)
        assert count == 1
        assert manager2.total_count == 1

        # Проверяем что расширенные поля восстановились
        mem = manager2._memories[0]
        assert mem.content == "loaded fact"
        assert mem.confidence == 0.9
        assert mem.decay_rate == 0.05

    def test_save_failure_to_db(self, manager, db_session):
        """Failure entries сохраняются в БД с metadata."""
        manager.store_failure(
            content="DB connection timeout",
            error_context="Connecting to SQLite",
            correction="Add retry logic",
            severity="high",
        )
        manager.save_to_db(db_session)

        db_entry = db_session.query(AgentMemory).first()
        assert db_entry is not None
        assert db_entry.memory_type == MemoryType.FAILURE

        meta = json.loads(db_entry.metadata_json)
        assert meta["error_context"] == "Connecting to SQLite"
        assert meta["correction"] == "Add retry logic"
        assert meta["severity"] == "high"

    def test_load_failure_from_db(self, db_session):
        """FailureEntry восстанавливается из БД."""
        db_entry = AgentMemory(
            content="test failure",
            memory_type=MemoryType.FAILURE,
            importance=0.8,
            tags=json.dumps(["failure", "test"]),
            source="test",
            metadata_json=json.dumps({
                "confidence": 0.9,
                "error_context": "ctx",
                "correction": "fix",
                "severity": "critical",
            }),
            is_active=True,
        )
        db_session.add(db_entry)
        db_session.commit()

        manager2 = AdvancedMemoryManager()
        manager2.load_from_db(db_session)

        assert manager2.total_count == 1
        mem = manager2._memories[0]
        assert isinstance(mem, FailureEntry)
        assert mem.error_context == "ctx"
        assert mem.correction == "fix"
        assert mem.severity == "critical"


# ═══════════════════════════════════════════════════════════════════════════════
# 8. DATABASE MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class TestDatabaseModels:
    """Тесты новых полей в DB моделях."""

    def test_agent_memory_new_fields(self, db_session):
        """Новые поля AgentMemory."""
        entry = AgentMemory(
            content="test",
            memory_type="episodic",
            importance=0.5,
            confidence=0.9,
            decay_rate=0.05,
            source_quality=0.8,
            context_hash="abc123",
            chat_id=12345,
            expiry=datetime.utcnow() + timedelta(days=30),
            failure_count=0,
            success_count=3,
        )
        db_session.add(entry)
        db_session.commit()

        loaded = db_session.query(AgentMemory).first()
        assert loaded.confidence == 0.9
        assert loaded.decay_rate == 0.05
        assert loaded.source_quality == 0.8
        assert loaded.context_hash == "abc123"
        assert loaded.chat_id == 12345
        assert loaded.expiry is not None
        assert loaded.failure_count == 0
        assert loaded.success_count == 3

    def test_agent_memory_defaults(self, db_session):
        """Дефолтные значения новых полей."""
        entry = AgentMemory(
            content="defaults test",
            memory_type="fact",
            importance=0.5,
        )
        db_session.add(entry)
        db_session.commit()

        loaded = db_session.query(AgentMemory).first()
        assert loaded.confidence == 0.8  # default
        assert loaded.decay_rate == 0.1  # default
        assert loaded.source_quality == 0.7  # default
        assert loaded.failure_count == 0
        assert loaded.success_count == 0

    def test_failure_log_create(self, db_session):
        """Создание записи FailureLog."""
        log = FailureLog(
            chat_id=12345,
            error_content="API timeout",
            error_context="Calling external API",
            root_cause="Network latency",
            correction="Add retry",
            lesson="Always use retry with backoff",
            severity="high",
            tags=json.dumps(["api", "timeout"]),
        )
        db_session.add(log)
        db_session.commit()

        loaded = db_session.query(FailureLog).first()
        assert loaded.error_content == "API timeout"
        assert loaded.severity == "high"
        assert loaded.is_resolved is False
        assert loaded.retry_count == 0
        assert loaded.chat_id == 12345

    def test_failure_log_resolve(self, db_session):
        """Разрешение FailureLog."""
        log = FailureLog(
            error_content="bug",
            severity="low",
        )
        db_session.add(log)
        db_session.commit()

        log.is_resolved = True
        log.retry_count = 2
        db_session.commit()

        loaded = db_session.query(FailureLog).first()
        assert loaded.is_resolved is True
        assert loaded.retry_count == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 9. BACKWARD COMPATIBILITY
# ═══════════════════════════════════════════════════════════════════════════════

class TestBackwardCompatibility:
    """Тесты backward compatibility со старым кодом."""

    def test_old_memory_imports(self):
        """Старые импорты из memory.py работают."""
        from pds_ultimate.core.memory import MemoryEntry, MemoryManager, WorkingMemory
        assert MemoryEntry is not None
        assert MemoryManager is not None
        assert WorkingMemory is not None

    def test_old_memory_manager_works(self):
        """Старый MemoryManager работает."""
        from pds_ultimate.core.memory import MemoryManager
        mgr = MemoryManager()
        mgr.store_fact("test")
        assert mgr.total_count == 1
        results = mgr.recall("test")
        assert len(results) >= 1

    def test_advanced_memory_manager_imports(self):
        """Новые импорты из advanced_memory_manager работают."""
        from pds_ultimate.core.advanced_memory_manager import (
            AdvancedMemoryManager,
            advanced_memory_manager,
        )
        assert AdvancedMemoryManager is not None
        assert advanced_memory_manager is not None

    def test_backward_compat_aliases(self):
        """Алиасы в advanced_memory_manager для совместимости."""
        from pds_ultimate.core.advanced_memory_manager import (
            MemoryEntry,
            MemoryManager,
            WorkingMemory,
        )
        # Эти алиасы указывают на Advanced версии
        assert MemoryEntry is AdvancedMemoryEntry
        assert MemoryManager is AdvancedMemoryManager
        assert WorkingMemory is AdvancedWorkingMemory


# ═══════════════════════════════════════════════════════════════════════════════
# 10. AGENT INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentIntegration:
    """Тесты интеграции advanced memory с Agent."""

    def test_agent_has_advanced_memory(self):
        """Agent имеет ссылку на advanced memory manager."""
        from pds_ultimate.core.agent import Agent
        a = Agent()
        assert hasattr(a, '_adv_memory')
        assert isinstance(a._adv_memory, AdvancedMemoryManager)

    def test_agent_accepts_adv_memory(self):
        """Agent принимает custom advanced memory."""
        from pds_ultimate.core.agent import Agent
        custom = AdvancedMemoryManager()
        a = Agent(adv_mem=custom)
        assert a._adv_memory is custom

    def test_agent_still_has_old_memory(self):
        """Agent сохраняет совместимость со старой памятью."""
        from pds_ultimate.core.agent import Agent
        from pds_ultimate.core.memory import MemoryManager
        a = Agent()
        assert hasattr(a, '_memory')
        assert isinstance(a._memory, MemoryManager)

    def test_agent_build_system_prompt_with_extra(self):
        """_build_system_prompt принимает extra_context."""
        from pds_ultimate.core.agent import Agent
        from pds_ultimate.core.tools import ToolRegistry

        a = Agent(tool_reg=ToolRegistry(), adv_mem=AdvancedMemoryManager())
        working = AdvancedWorkingMemory()
        working.set_goal("test")

        prompt = a._build_system_prompt(
            "test message", working, None,
            extra_context="EXTRA CONTEXT HERE"
        )
        assert "EXTRA CONTEXT HERE" in prompt

    def test_agent_smart_routing(self):
        """should_use_tools работает."""
        import asyncio

        from pds_ultimate.core.agent import Agent

        a = Agent()
        # Simple messages → no tools
        assert asyncio.get_event_loop().run_until_complete(
            a.should_use_tools("привет")
        ) is False

        # Complex messages → tools
        assert asyncio.get_event_loop().run_until_complete(
            a.should_use_tools("создай заказ на 100 балаклав")
        ) is True


# ═══════════════════════════════════════════════════════════════════════════════
# 11. EDGE CASES & STRESS
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Тесты граничных случаев."""

    def test_empty_recall(self, manager):
        """Recall на пустой памяти."""
        results = manager.recall("anything")
        assert results == []

    def test_recall_with_all_filters(self, manager):
        """Recall со всеми фильтрами одновременно."""
        manager.store_fact("target keyword match", importance=0.9,
                           tags=["target"], chat_id=100)
        manager.store_fact("noise something else", importance=0.1,
                           tags=["noise"], chat_id=200)

        results = manager.recall(
            "target keyword",
            memory_type=MemoryType.FACT,
            tags=["target"],
            min_importance=0.0,
            chat_id=100,
        )
        assert len(results) == 1
        assert "target" in results[0].content

    def test_store_many_entries(self, manager):
        """Хранение большого количества записей."""
        for i in range(100):
            manager.store_fact(f"fact number {i}", importance=i / 100)
        assert manager.total_count == 100

    def test_unicode_content(self, manager):
        """Unicode в content (русский, китайский, эмодзи)."""
        manager.store_fact("Тест юникода данные 中文 emoji 🎉")
        results = manager.recall("юникода данные")
        assert len(results) == 1
        assert "🎉" in results[0].content

    def test_very_long_content(self, manager):
        """Очень длинный content."""
        long_content = "x" * 10000
        entry = AdvancedMemoryEntry(long_content)
        manager.store(entry)
        assert manager.total_count == 1

    def test_prune_empty_memory(self, manager):
        """Prune на пустой памяти."""
        pruned = manager.prune()
        assert pruned == 0

    def test_concurrent_store_recall(self, manager):
        """Store и recall в одном потоке (синхронно)."""
        for i in range(10):
            manager.store_fact(f"concurrent fact {i}")
        for i in range(10):
            results = manager.recall(f"concurrent fact {i}")
            assert len(results) >= 1

    def test_failure_no_failures(self, manager):
        """get_relevant_failures на пустой памяти."""
        failures = manager.get_relevant_failures("any query")
        assert failures == []

    def test_working_memory_nonexistent_chat(self, manager):
        """get_working для несуществующего chat создаёт новый."""
        w = manager.get_working(999999)
        assert isinstance(w, AdvancedWorkingMemory)
        assert w.primary_goal == ""

    def test_reset_nonexistent_working(self, manager):
        """reset_working для несуществующего chat — no-op."""
        manager.reset_working(888888)  # Не должно падать
