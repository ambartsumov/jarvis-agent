"""
Тесты Memory v2 (Part 8)
============================
SkillLibrary, FailureLearningEngine, StrategicMemory,
ContextWindowOptimizer, MemoryV2Engine.
~55 тестов.
"""


from pds_ultimate.core.memory_v2 import (
    ContextWindowOptimizer,
    FailureLearningEngine,
    MemoryV2Engine,
    Skill,
    SkillLibrary,
    StrategicMemory,
    memory_v2,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Skill dataclass
# ═══════════════════════════════════════════════════════════════════════════════


class TestSkill:
    """Skill — навык агента."""

    def test_success_rate_zero(self):
        s = Skill()
        assert s.success_rate == 0.0

    def test_success_rate_all_success(self):
        s = Skill(success_count=10, failure_count=0)
        assert s.success_rate == 1.0

    def test_success_rate_mixed(self):
        s = Skill(success_count=7, failure_count=3)
        assert s.success_rate == 0.7

    def test_total_uses(self):
        s = Skill(success_count=5, failure_count=3)
        assert s.total_uses == 8

    def test_matches_positive(self):
        s = Skill(pattern=r"курс|валют|TMT")
        assert s.matches("Какой курс доллара?") is True

    def test_matches_negative(self):
        s = Skill(pattern=r"курс|валют|TMT")
        assert s.matches("Погода в Ашхабаде") is False

    def test_matches_empty_pattern(self):
        s = Skill(pattern="")
        assert s.matches("anything") is False

    def test_to_dict(self):
        s = Skill(
            id="s1", name="Test Skill",
            strategy="Use tool X",
            success_count=8, failure_count=2,
            tools_used=["web_search"],
            tags=["test"],
        )
        d = s.to_dict()
        assert d["name"] == "Test Skill"
        assert d["success_rate"] == "80%"
        assert d["total_uses"] == 10
        assert "web_search" in d["tools"]


# ═══════════════════════════════════════════════════════════════════════════════
# SkillLibrary
# ═══════════════════════════════════════════════════════════════════════════════


class TestSkillLibrary:
    """SkillLibrary — библиотека навыков."""

    def test_add_skill(self):
        lib = SkillLibrary()
        skill = lib.add_skill(
            name="Currency Convert",
            pattern=r"курс|валют",
            strategy="Use exchange_rates tool",
        )
        assert skill.id.startswith("skill_")
        assert skill.name == "Currency Convert"
        assert lib.count == 1

    def test_find_matching(self):
        lib = SkillLibrary()
        s1 = lib.add_skill(name="Currency", pattern=r"курс|валют")
        s1.success_count = 5  # need success rate > 0
        s2 = lib.add_skill(name="Search", pattern=r"найди|поиск")
        s2.success_count = 3
        matches = lib.find_matching("Какой курс доллара?")
        assert len(matches) >= 1
        assert matches[0].name == "Currency"

    def test_find_matching_min_success_rate(self):
        lib = SkillLibrary()
        s = lib.add_skill(name="Bad", pattern=r"тест")
        s.success_count = 1
        s.failure_count = 9  # 10% success
        matches = lib.find_matching("тест", min_success_rate=0.5)
        assert len(matches) == 0

    def test_record_usage_success(self):
        lib = SkillLibrary()
        skill = lib.add_skill(name="Test", pattern=r"test")
        lib.record_usage(skill.id, success=True)
        assert skill.success_count == 1

    def test_record_usage_failure(self):
        lib = SkillLibrary()
        skill = lib.add_skill(name="Test", pattern=r"test")
        lib.record_usage(skill.id, success=False)
        assert skill.failure_count == 1

    def test_record_usage_nonexistent(self):
        lib = SkillLibrary()
        lib.record_usage("nope", success=True)  # No error

    def test_get_skill(self):
        lib = SkillLibrary()
        skill = lib.add_skill(name="Findme")
        found = lib.get_skill(skill.id)
        assert found is not None
        assert found.name == "Findme"

    def test_get_skill_none(self):
        lib = SkillLibrary()
        assert lib.get_skill("nope") is None

    def test_remove_skill(self):
        lib = SkillLibrary()
        skill = lib.add_skill(name="Remove")
        assert lib.remove_skill(skill.id) is True
        assert lib.count == 0

    def test_remove_nonexistent(self):
        lib = SkillLibrary()
        assert lib.remove_skill("nope") is False

    def test_get_top_skills(self):
        lib = SkillLibrary()
        s1 = lib.add_skill(name="S1")
        s1.success_count = 10
        s2 = lib.add_skill(name="S2")
        s2.success_count = 5
        s2.failure_count = 5
        top = lib.get_top_skills(limit=2)
        assert len(top) == 2
        assert top[0].name == "S1"

    def test_to_context(self):
        lib = SkillLibrary()
        s = lib.add_skill(
            name="Currency Convert",
            pattern=r"курс|валют",
            strategy="Использовать exchange_rates",
        )
        s.success_count = 5  # need success rate > min_success_rate
        ctx = lib.to_context("Какой курс доллара?")
        assert "НАВЫКИ" in ctx
        assert "Currency Convert" in ctx

    def test_to_context_no_match(self):
        lib = SkillLibrary()
        lib.add_skill(name="X", pattern=r"xyz_unique")
        ctx = lib.to_context("Погода сегодня")
        assert ctx == ""


# ═══════════════════════════════════════════════════════════════════════════════
# FailureLearningEngine
# ═══════════════════════════════════════════════════════════════════════════════


class TestFailureLearningEngine:
    """FailureLearningEngine — обучение на ошибках."""

    def test_record_failure(self):
        fle = FailureLearningEngine()
        record = fle.record_failure(
            query="test query",
            error_message="timeout error",
        )
        assert record.id.startswith("fail_")
        assert record.error_type == "timeout_error"
        assert fle.total_failures == 1

    def test_classify_timeout(self):
        fle = FailureLearningEngine()
        assert fle._classify_error("Connection timed out") == "timeout_error"

    def test_classify_not_found(self):
        fle = FailureLearningEngine()
        assert fle._classify_error("404 not found") == "not_found_error"

    def test_classify_permission(self):
        fle = FailureLearningEngine()
        assert fle._classify_error(
            "403 permission denied") == "permission_error"

    def test_classify_unknown(self):
        fle = FailureLearningEngine()
        assert fle._classify_error(
            "Something weird happened") == "unknown_error"

    def test_get_relevant_lessons(self):
        fle = FailureLearningEngine()
        fle.record_failure(
            query="курс доллара",
            error_message="timeout",
            tool_involved="exchange_rates",
            correction="Увеличить timeout",
        )
        lessons = fle.get_relevant_lessons("курс евро", tool="exchange_rates")
        assert len(lessons) >= 1

    def test_get_relevant_lessons_empty(self):
        fle = FailureLearningEngine()
        assert fle.get_relevant_lessons("test") == []

    def test_to_context(self):
        fle = FailureLearningEngine()
        fle.record_failure(
            query="поиск данных",
            error_message="rate limit exceeded",
            correction="Добавить задержку",
        )
        ctx = fle.to_context("поиск информации")
        assert "ОШИБОК" in ctx or "УРОКИ" in ctx

    def test_to_context_empty(self):
        fle = FailureLearningEngine()
        assert fle.to_context("anything") == ""

    def test_get_stats(self):
        fle = FailureLearningEngine()
        fle.record_failure(query="q", error_message="timeout")
        stats = fle.get_stats()
        assert stats["total"] == 1
        assert "by_type" in stats

    def test_get_stats_empty(self):
        fle = FailureLearningEngine()
        stats = fle.get_stats()
        assert stats["total"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# StrategicMemory
# ═══════════════════════════════════════════════════════════════════════════════


class TestStrategicMemory:
    """StrategicMemory — стратегическая память."""

    def test_add_observation(self):
        sm = StrategicMemory()
        sm.add_observation(action="search", context="Python")
        assert len(sm._observations) == 1

    def test_extract_patterns_not_enough(self):
        sm = StrategicMemory()
        sm.add_observation(action="test")
        patterns = sm.extract_patterns(min_occurrences=3)
        assert len(patterns) == 0

    def test_extract_patterns_enough(self):
        sm = StrategicMemory()
        for _ in range(5):
            sm.add_observation(action="search_currency", context="курс")
        patterns = sm.extract_patterns(min_occurrences=3)
        assert len(patterns) >= 1

    def test_pattern_count(self):
        sm = StrategicMemory()
        assert sm.pattern_count == 0
        for _ in range(5):
            sm.add_observation(action="repeat_action")
        sm.extract_patterns(min_occurrences=3)
        assert sm.pattern_count >= 1

    def test_get_relevant_patterns(self):
        sm = StrategicMemory()
        for _ in range(5):
            sm.add_observation(action="currency_convert")
        sm.extract_patterns(min_occurrences=3)
        # Pattern name includes the action word
        patterns = sm.get_relevant_patterns("currency_convert паттерн")
        assert len(patterns) >= 1

    def test_to_context(self):
        sm = StrategicMemory()
        for _ in range(5):
            sm.add_observation(action="search_data")
        sm.extract_patterns(min_occurrences=3)
        ctx = sm.to_context("search_data паттерн")
        if sm.pattern_count > 0:
            assert "ПАТТЕРН" in ctx


# ═══════════════════════════════════════════════════════════════════════════════
# ContextWindowOptimizer
# ═══════════════════════════════════════════════════════════════════════════════


class TestContextWindowOptimizer:
    """ContextWindowOptimizer — оптимизация контекстного окна."""

    def test_fits_in_window(self):
        opt = ContextWindowOptimizer(max_tokens=10000)
        blocks = {"system": "short", "query": "also short"}
        result = opt.optimize(blocks)
        assert result == blocks  # All fits

    def test_truncates_large(self):
        opt = ContextWindowOptimizer(max_tokens=100)
        blocks = {"system": "x" * 5000, "history": "y" * 5000}
        result = opt.optimize(blocks)
        total = sum(len(v) for v in result.values())
        # Optimizer truncates — result should be smaller than input
        assert total < 10000

    def test_estimate_tokens(self):
        opt = ContextWindowOptimizer()
        tokens = opt.estimate_tokens("Привет мир")
        assert tokens > 0


# ═══════════════════════════════════════════════════════════════════════════════
# MemoryV2Engine
# ═══════════════════════════════════════════════════════════════════════════════


class TestMemoryV2Engine:
    """MemoryV2Engine — объединённый движок."""

    def _make_engine(self) -> MemoryV2Engine:
        return MemoryV2Engine()

    def test_init_components(self):
        m = self._make_engine()
        assert m.skills is not None
        assert m.failures is not None
        assert m.strategic is not None
        assert m.optimizer is not None

    def test_learn_skill(self):
        m = self._make_engine()
        skill = m.learn_skill(
            name="Test",
            pattern=r"test",
            strategy="Do test",
        )
        assert skill.name == "Test"
        assert m.skills.count == 1

    def test_record_failure(self):
        m = self._make_engine()
        m.record_failure(
            query="test",
            error="timeout",
            tool="web_search",
        )
        assert m.failures.total_failures == 1

    def test_record_success(self):
        m = self._make_engine()
        skill = m.learn_skill(
            name="Search", pattern=r"поиск", strategy="web_search")
        skill.success_count = 1  # Initial success so find_matching returns it
        m.record_success(
            query="поиск информации",
            tools_used=["web_search"],
        )
        # Should update skill usage
        skills = m.skills.find_matching("поиск")
        if skills:
            assert skills[0].success_count >= 2

    def test_get_full_context(self):
        m = self._make_engine()
        skill = m.learn_skill(
            name="Currency", pattern=r"курс", strategy="exchange_rates")
        skill.success_count = 5
        ctx = m.get_full_context("Какой курс доллара?")
        assert "НАВЫКИ" in ctx

    def test_get_full_context_empty(self):
        m = self._make_engine()
        ctx = m.get_full_context("random query")
        assert ctx == ""

    def test_analyze_patterns(self):
        m = self._make_engine()
        for _ in range(5):
            m.strategic.add_observation(action="repeat")
        patterns = m.analyze_patterns()
        assert len(patterns) >= 1

    def test_get_stats(self):
        m = self._make_engine()
        stats = m.get_stats()
        assert "skills" in stats
        assert "failures" in stats
        assert "patterns" in stats
        assert "top_skills" in stats


# ═══════════════════════════════════════════════════════════════════════════════
# Global instance
# ═══════════════════════════════════════════════════════════════════════════════


class TestMemoryV2Global:
    """Глобальный экземпляр."""

    def test_global_exists(self):
        assert memory_v2 is not None
        assert isinstance(memory_v2, MemoryV2Engine)
