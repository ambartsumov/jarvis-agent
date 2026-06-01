"""
Tests for UnifiedMemory — PDS-Ultimate Unified Memory System
==============================================================
"""

import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

from pds_ultimate.core.unified_memory import (
    MemoryEntry,
    MemoryLayer,
    MemoryType,
    Skill,
    UnifiedMemory,
    WorkingMemory,
    classify_error,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def memory():
    """Create a fresh UnifiedMemory with temp DB."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    mem = UnifiedMemory(db_path=db_path)
    yield mem
    # Cleanup
    try:
        os.unlink(db_path)
    except OSError:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# 1. MemoryEntry TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestMemoryEntry:
    def test_create_basic(self):
        entry = MemoryEntry(content="Test memory entry")
        assert entry.content == "Test memory entry"
        assert entry.memory_type == MemoryType.EPISODIC
        assert entry.layer == MemoryLayer.LONG_TERM
        assert entry.importance == 0.5
        assert entry.confidence == 0.8
        assert entry._keywords  # Should have extracted keywords

    def test_keywords_extraction(self):
        entry = MemoryEntry(
            content="пользователь предпочитает короткие ответы")
        assert "пользователь" in entry._keywords
        assert "предпочитает" in entry._keywords
        assert "короткие" in entry._keywords
        assert "ответы" in entry._keywords

    def test_bigrams_extraction(self):
        entry = MemoryEntry(content="quick brown fox jumps")
        assert len(entry._bigrams) > 0

    def test_content_hash_dedup(self):
        e1 = MemoryEntry(content="Hello World")
        e2 = MemoryEntry(content="hello world")
        assert e1._content_hash == e2._content_hash

    def test_effective_importance_fresh(self):
        entry = MemoryEntry(
            content="test", importance=1.0, confidence=1.0, decay_rate=0.1
        )
        eff = entry.effective_importance()
        assert eff > 0.7  # Fresh entry, high importance

    def test_effective_importance_expired(self):
        entry = MemoryEntry(
            content="test",
            expires_at=time.time() - 100,  # expired
        )
        assert entry.is_expired
        assert entry.effective_importance() == 0.0

    def test_touch(self):
        entry = MemoryEntry(content="test")
        old_count = entry.access_count
        entry.touch()
        assert entry.access_count == old_count + 1

    def test_mark_success(self):
        entry = MemoryEntry(content="test", confidence=0.5)
        entry.mark_success()
        assert entry.success_count == 1
        assert entry.confidence > 0.5

    def test_mark_failure(self):
        entry = MemoryEntry(content="test", confidence=0.8)
        entry.mark_failure()
        assert entry.failure_count == 1
        assert entry.confidence < 0.8

    def test_promote(self):
        entry = MemoryEntry(
            content="test", layer=MemoryLayer.SHORT_TERM,
            expires_at=time.time() + 1000,
        )
        entry.promote()
        assert entry.layer == MemoryLayer.LONG_TERM
        assert entry.expires_at is None

    def test_relevance_to(self):
        entry = MemoryEntry(content="купить балаклавы в Китае оптом")
        score = entry.relevance_to("балаклавы оптом")
        assert score > 0.3  # Should have keyword overlap

    def test_relevance_unrelated(self):
        entry = MemoryEntry(content="купить балаклавы в Китае оптом")
        score = entry.relevance_to("погода в Лондоне")
        assert score < 0.1  # Unrelated

    def test_to_dict(self):
        entry = MemoryEntry(content="test fact", memory_type=MemoryType.FACT)
        d = entry.to_dict()
        assert d["content"] == "test fact"
        assert d["memory_type"] == "fact"
        assert "importance" in d
        assert "confidence" in d

    def test_success_rate(self):
        entry = MemoryEntry(content="test")
        entry.success_count = 8
        entry.failure_count = 2
        assert entry.success_rate == 0.8


# ═══════════════════════════════════════════════════════════════════════════════
# 2. WorkingMemory TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorkingMemory:
    def test_set_goal(self):
        wm = WorkingMemory(chat_id=123)
        wm.set_goal("Найти поставщика")
        assert wm.primary_goal == "Найти поставщика"
        assert wm.plan == []

    def test_plan_steps(self):
        wm = WorkingMemory(chat_id=123)
        wm.set_goal("Multi-step task")
        idx0 = wm.add_plan_step("Search suppliers")
        idx1 = wm.add_plan_step("Compare prices", depends_on=[0])
        idx2 = wm.add_plan_step("Place order", depends_on=[1])

        assert len(wm.plan) == 3

        # Only step 0 should be ready
        ready = wm.get_ready_steps()
        assert len(ready) == 1
        assert ready[0][0] == 0

        # Complete step 0
        wm.complete_step(0, "Found 3 suppliers")
        ready = wm.get_ready_steps()
        assert len(ready) == 1
        assert ready[0][0] == 1

        # Complete step 1
        wm.complete_step(1, "Supplier A is cheapest")
        ready = wm.get_ready_steps()
        assert len(ready) == 1
        assert ready[0][0] == 2

    def test_add_note(self):
        wm = WorkingMemory(chat_id=123)
        wm.add_note("Important observation")
        assert len(wm.scratchpad) == 1
        assert wm.scratchpad[0] == "Important observation"

    def test_scratchpad_limit(self):
        wm = WorkingMemory(chat_id=123)
        for i in range(50):
            wm.add_note(f"Note {i}")
        assert len(wm.scratchpad) == WorkingMemory.MAX_SCRATCHPAD

    def test_add_tool_result(self):
        wm = WorkingMemory(chat_id=123)
        wm.add_tool_result("web_search", "Found 10 results", True)
        assert len(wm.tool_results) == 1
        assert wm.tool_results[0]["tool"] == "web_search"
        assert wm.tool_results[0]["success"] is True

    def test_hypothesis(self):
        wm = WorkingMemory(chat_id=123)
        idx = wm.add_hypothesis("Supplier A is reliable", 0.7)
        assert len(wm.hypotheses) == 1
        assert wm.hypotheses[idx]["confidence"] == 0.7

    def test_context_summary(self):
        wm = WorkingMemory(chat_id=123)
        wm.set_goal("Test goal")
        wm.add_plan_step("Step 1")
        wm.add_note("Note 1")
        summary = wm.get_context_summary()
        assert "Test goal" in summary
        assert "Step 1" in summary

    def test_reset(self):
        wm = WorkingMemory(chat_id=123)
        wm.set_goal("Goal")
        wm.add_note("Note")
        wm.reset()
        assert wm.primary_goal == ""
        assert wm.scratchpad == []

    def test_fail_step(self):
        wm = WorkingMemory(chat_id=123)
        wm.add_plan_step("Risky step")
        wm.fail_step(0, "Connection timeout")
        assert wm.plan[0]["status"] == "failed"
        assert "timeout" in wm.plan[0]["result"]


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Skill TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestSkill:
    def test_create(self):
        skill = Skill(
            id="s1", name="Web Search",
            pattern=r"найди|поиск|search",
            strategy="Use web_search tool",
        )
        assert skill.name == "Web Search"

    def test_matches(self):
        skill = Skill(
            id="s1", name="Web Search",
            pattern=r"найди|поиск|search",
            strategy="Use web_search tool",
        )
        assert skill.matches("Найди информацию")
        assert skill.matches("search for data")
        assert not skill.matches("расскажи анекдот")

    def test_success_rate(self):
        skill = Skill(id="s1", name="test")
        skill.success_count = 7
        skill.failure_count = 3
        assert skill.success_rate == 0.7

    def test_to_dict(self):
        skill = Skill(id="s1", name="Test Skill")
        d = skill.to_dict()
        assert d["id"] == "s1"
        assert d["name"] == "Test Skill"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. UnifiedMemory TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestUnifiedMemory:
    def test_add_and_search(self, memory):
        memory.add("пользователь предпочитает короткие ответы",
                   MemoryType.PREFERENCE, importance=0.8)
        memory.add("балаклавы заказывали партией 100 штук",
                   MemoryType.FACT, importance=0.7)

        results = memory.search("короткие ответы")
        assert len(results) >= 1
        assert any("короткие" in r.content for r in results)

    def test_deduplication(self, memory):
        memory.add("test fact", MemoryType.FACT)
        memory.add("test fact", MemoryType.FACT)
        assert memory.get_stats()["total"] == 1

    def test_search_by_type(self, memory):
        memory.add("fact 1", MemoryType.FACT)
        memory.add("preference 1", MemoryType.PREFERENCE)
        memory.add("failure 1", MemoryType.FAILURE)

        facts = memory.search("fact", memory_type=MemoryType.FACT)
        # Should only return facts
        for m in facts:
            assert m.memory_type == MemoryType.FACT

    def test_search_by_chat_id(self, memory):
        memory.add("global fact", MemoryType.FACT, chat_id=None)
        memory.add("user 1 fact", MemoryType.FACT, chat_id=100)
        memory.add("user 2 fact", MemoryType.FACT, chat_id=200)

        # Search for user 100 should include global + user 100
        results = memory.search("fact", chat_id=100)
        for r in results:
            assert r.chat_id is None or r.chat_id == 100

    def test_recall(self, memory):
        memory.add("поставщик Alibaba надёжный", MemoryType.FACT,
                   importance=0.9)
        memory.add("[timeout] Alibaba API failed",
                   MemoryType.FAILURE, error_context="API call")

        results = memory.recall("Alibaba поставщик")
        assert len(results) >= 1

    def test_get_context(self, memory):
        memory.add("пользователь предпочитает формальный тон",
                   MemoryType.PREFERENCE, importance=0.8)
        ctx = memory.get_context("как отвечать")
        assert "ПАМЯТЬ" in ctx or len(ctx) > 0

    def test_record_failure(self, memory):
        entry = memory.record_failure(
            query="search for products",
            error="Connection timeout after 30s",
            tool="web_search",
            correction="Use shorter timeout and retry",
            severity="medium",
        )
        assert entry.memory_type == MemoryType.FAILURE
        assert "timeout" in entry.content
        assert entry.correction == "Use shorter timeout and retry"

    def test_get_failure_lessons(self, memory):
        memory.record_failure(
            query="search Alibaba",
            error="Rate limit exceeded",
            tool="web_search",
            correction="Add delay between requests",
        )
        lessons = memory.get_failure_lessons(
            "search Alibaba", tool="web_search")
        assert len(lessons) >= 1

    def test_skills(self, memory):
        skill = memory.add_skill(
            name="Web Search",
            pattern=r"найди|поиск|search",
            strategy="Use web_search tool with specific query",
            tools=["web_search"],
        )
        assert skill.id.startswith("skill_")

        # Find matching skills (min_success_rate=0 since new skill has no usage)
        matches = memory.find_skills("найди информацию", min_success_rate=0.0)
        assert len(matches) >= 1

    def test_skill_usage(self, memory):
        skill = memory.add_skill(
            name="Test", pattern=r"test", strategy="testing",
        )
        memory.record_skill_usage(skill.id, success=True)
        memory.record_skill_usage(skill.id, success=True)
        memory.record_skill_usage(skill.id, success=False)

        updated = memory._skills[skill.id]
        assert updated.success_count == 2
        assert updated.failure_count == 1

    def test_working_memory(self, memory):
        wm = memory.get_working(123)
        assert isinstance(wm, WorkingMemory)
        assert wm.chat_id == 123

        # Same chat_id returns same instance
        wm2 = memory.get_working(123)
        assert wm is wm2

        # Different chat_id returns different instance
        wm3 = memory.get_working(456)
        assert wm3 is not wm

    def test_reset_working(self, memory):
        wm = memory.get_working(123)
        wm.set_goal("test")
        memory.reset_working(123)
        wm_new = memory.get_working(123)
        assert wm_new.primary_goal == ""

    def test_persistence(self, memory):
        memory.add("persistent fact", MemoryType.FACT, importance=0.9)
        memory.add_skill(
            name="Persistent Skill", pattern=r"test",
            strategy="testing persistence",
        )
        memory.save_to_db()

        # Create new instance with same DB
        memory2 = UnifiedMemory(db_path=memory._db_path)
        loaded = memory2.load_from_db()
        assert loaded >= 1
        assert memory2.get_stats()["total"] >= 1
        assert len(memory2._skills) >= 1

    def test_prune_expired(self, memory):
        memory.add("will expire", MemoryType.FACT,
                   ttl_seconds=1)
        time.sleep(1.1)
        pruned = memory.prune()
        assert pruned >= 1

    def test_consolidation(self, memory):
        # Force consolidation by setting low interval
        memory.CONSOLIDATION_INTERVAL = 5
        for i in range(6):
            memory.add(f"fact number {i}", MemoryType.FACT)
        # Should have triggered consolidation (no duplicates to remove though)
        assert memory.get_stats()["total"] == 6

    def test_stats(self, memory):
        memory.add("fact 1", MemoryType.FACT)
        memory.add("pref 1", MemoryType.PREFERENCE)
        stats = memory.get_stats()
        assert stats["total"] == 2
        assert "by_type" in stats
        assert "by_layer" in stats
        assert "skills" in stats

    def test_short_term_ttl(self, memory):
        entry = memory.add(
            "temporary info", MemoryType.FACT,
            layer=MemoryLayer.SHORT_TERM,
        )
        assert entry.expires_at is not None
        assert entry.layer == MemoryLayer.SHORT_TERM


# ═══════════════════════════════════════════════════════════════════════════════
# 5. classify_error TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestClassifyError:
    def test_timeout(self):
        assert classify_error("Connection timed out") == "timeout"

    def test_not_found(self):
        assert classify_error("404 page not found") == "not_found"

    def test_rate_limit(self):
        assert classify_error("429 rate limit exceeded") == "rate_limit"

    def test_parse_error(self):
        assert classify_error("JSON parse error") == "parse_error"

    def test_network(self):
        assert classify_error("Network connection failed") == "network"

    def test_unknown(self):
        assert classify_error("something weird happened") == "unknown"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. BACKWARD COMPATIBILITY TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestBackwardCompat:
    """Ensure old imports still work."""

    def test_memory_module_imports(self):
        from pds_ultimate.core.memory import (
            MemoryManager,
            memory_manager,
        )
        assert MemoryManager is UnifiedMemory
        assert memory_manager is not None

    def test_memory_v2_imports(self):
        from pds_ultimate.core.memory_v2 import (
            MemoryV2Engine,
            memory_v2,
        )
        assert MemoryV2Engine is UnifiedMemory
        assert memory_v2 is not None

    def test_advanced_memory_imports(self):
        from pds_ultimate.core.advanced_memory import (
            AdvancedMemoryEntry,
        )
        assert AdvancedMemoryEntry is MemoryEntry

    def test_advanced_memory_manager_imports(self):
        from pds_ultimate.core.advanced_memory_manager import (
            AdvancedMemoryManager,
        )
        assert AdvancedMemoryManager is UnifiedMemory


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
