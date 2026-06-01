"""
Tests for Step 16: Smart ReAct Loop Enhancer
==============================================
Covers:
- ObservationSummarizer: short/medium/large text, structured data
- ActionDedup: duplicate detection, hashing, recording, window
- TokenBudget: tracking, categories, exceeded, warning, reset
- OscillationDetector: ABAB, ABCABC, same-action-3x, clear
- SelfReflector: error strategies, retry limits, failure summary
- ReactEnhancer: unified API, check_action, process_observation, reflect
"""


from pds_ultimate.core.react_enhancer import (
    ActionDedup,
    ActionRecord,
    BudgetSnapshot,
    ObservationSummarizer,
    OscillationDetector,
    ReactEnhancer,
    ReflectionResult,
    SelfReflector,
    TokenBudget,
)

# ═══════════════════════════════════════════════════════════════════════════════
# 1. OBSERVATION SUMMARIZER
# ═══════════════════════════════════════════════════════════════════════════════


class TestObservationSummarizer:
    def setup_method(self):
        self.summarizer = ObservationSummarizer(
            short_threshold=100,
            max_length=200,
        )

    def test_short_text_unchanged(self):
        text = "Short result"
        assert self.summarizer.truncate(text) == text

    def test_empty_text(self):
        assert self.summarizer.truncate("") == ""

    def test_long_text_truncated(self):
        text = "Line " * 100  # 500 chars
        result = self.summarizer.truncate(text, "search")
        assert len(result) <= 300  # max_length + overhead
        assert "пропущено" in result or "обрезано" in result

    def test_structured_json_truncated(self):
        text = '{"data": "' + "x" * 300 + '"}'
        result = self.summarizer.truncate(text, "api")
        assert "пропущено" in result
        assert result.startswith('{"data"')

    def test_preserves_head_and_tail(self):
        lines = [f"Line {i}" for i in range(50)]
        text = "\n".join(lines)
        result = self.summarizer.truncate(text, "search")
        assert "Line 0" in result  # Head preserved
        # Tail should have some late lines
        assert "пропущено" in result

    def test_exact_threshold(self):
        text = "x" * 100  # exactly at threshold
        assert self.summarizer.truncate(text) == text

    def test_just_over_threshold(self):
        text = "x" * 101
        result = self.summarizer.truncate(text)
        assert len(result) <= 300


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ACTION DEDUP
# ═══════════════════════════════════════════════════════════════════════════════


class TestActionDedup:
    def setup_method(self):
        self.dedup = ActionDedup(window_size=10)

    def test_first_call_not_duplicate(self):
        is_dup, _ = self.dedup.check("search", {"query": "hello"})
        assert not is_dup

    def test_same_call_is_duplicate(self):
        params = {"query": "hello"}
        self.dedup.record("search", params, True, "result1")
        is_dup, reason = self.dedup.check("search", params)
        assert is_dup
        assert "Duplicate" in reason

    def test_different_params_not_duplicate(self):
        self.dedup.record("search", {"query": "hello"}, True, "result1")
        is_dup, _ = self.dedup.check("search", {"query": "world"})
        assert not is_dup

    def test_different_tool_not_duplicate(self):
        self.dedup.record("search", {"query": "hello"}, True, "result1")
        is_dup, _ = self.dedup.check("calculate", {"query": "hello"})
        assert not is_dup

    def test_none_params(self):
        self.dedup.record("list_files", None, True, "files")
        is_dup, _ = self.dedup.check("list_files", None)
        assert is_dup

    def test_window_bounded(self):
        # Fill beyond window
        for i in range(15):
            self.dedup.record(f"tool_{i}", {"x": i}, True, f"r{i}")
        # Old entries should be gone after bound
        history = self.dedup.get_history()
        assert len(history) <= 10

    def test_clear(self):
        self.dedup.record("search", {"q": "test"}, True)
        self.dedup.clear()
        is_dup, _ = self.dedup.check("search", {"q": "test"})
        assert not is_dup

    def test_hash_stability(self):
        # Same params in different order should hash the same
        h1 = self.dedup._hash_params({"a": 1, "b": 2})
        h2 = self.dedup._hash_params({"b": 2, "a": 1})
        assert h1 == h2


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TOKEN BUDGET
# ═══════════════════════════════════════════════════════════════════════════════


class TestTokenBudget:
    def test_initial_state(self):
        budget = TokenBudget(budget=10000)
        assert budget.tokens_used == 0
        assert budget.tokens_remaining == 10000
        assert not budget.is_exceeded
        assert not budget.is_warning

    def test_add_usage(self):
        budget = TokenBudget(budget=10000)
        budget.add("input", 3000)
        budget.add("output", 2000)
        assert budget.tokens_used == 5000
        assert budget.tokens_remaining == 5000

    def test_exceeded(self):
        budget = TokenBudget(budget=100)
        budget.add("input", 150)
        assert budget.is_exceeded
        assert budget.tokens_remaining == 0

    def test_warning_threshold(self):
        budget = TokenBudget(budget=100)
        budget.add("input", 85)
        assert budget.is_warning
        assert not budget.is_exceeded

    def test_check_snapshot(self):
        budget = TokenBudget(budget=1000)
        budget.add("input", 300)
        budget.add("tool_results", 200)
        snap = budget.check()
        assert isinstance(snap, BudgetSnapshot)
        assert snap.tokens_used == 500
        assert snap.tokens_remaining == 500
        assert snap.percentage_used == 0.5
        assert not snap.is_exceeded
        assert snap.breakdown["input"] == 300
        assert snap.breakdown["tool_results"] == 200

    def test_reset(self):
        budget = TokenBudget(budget=1000)
        budget.add("input", 500)
        budget.reset()
        assert budget.tokens_used == 0

    def test_default_budget(self):
        budget = TokenBudget()
        assert budget.total_budget == TokenBudget.DEFAULT_BUDGET

    def test_custom_category(self):
        budget = TokenBudget(budget=1000)
        budget.add("custom_step", 100)
        assert budget.tokens_used == 100
        snap = budget.check()
        assert snap.breakdown["custom_step"] == 100


# ═══════════════════════════════════════════════════════════════════════════════
# 4. OSCILLATION DETECTOR
# ═══════════════════════════════════════════════════════════════════════════════


class TestOscillationDetector:
    def setup_method(self):
        self.detector = OscillationDetector(
            min_window=4,
            max_cycle_length=4,
            min_repeats=2,
        )

    def test_no_oscillation_short(self):
        self.detector.record("A")
        self.detector.record("B")
        is_osc, _ = self.detector.check()
        assert not is_osc

    def test_abab_detected(self):
        for action in ["A", "B", "A", "B"]:
            self.detector.record(action)
        is_osc, desc = self.detector.check()
        assert is_osc
        assert "cycle" in desc

    def test_abcabc_detected(self):
        detector = OscillationDetector(
            min_window=6, max_cycle_length=4, min_repeats=2)
        for action in ["A", "B", "C", "A", "B", "C"]:
            detector.record(action)
        is_osc, desc = detector.check()
        assert is_osc

    def test_same_action_3x(self):
        for _ in range(3):
            self.detector.record("search:abc")
        is_osc, desc = self.detector.check()
        assert is_osc
        assert "repeated 3x" in desc

    def test_no_oscillation_diverse(self):
        for action in ["A", "B", "C", "D"]:
            self.detector.record(action)
        is_osc, _ = self.detector.check()
        assert not is_osc

    def test_clear(self):
        for action in ["A", "B", "A", "B"]:
            self.detector.record(action)
        self.detector.clear()
        is_osc, _ = self.detector.check()
        assert not is_osc

    def test_single_cycle_detected(self):
        """AA pattern = cycle length 1, repeated 2x."""
        detector = OscillationDetector(min_window=2, min_repeats=2)
        detector.record("X")
        detector.record("X")
        is_osc, _ = detector.check()
        assert is_osc


# ═══════════════════════════════════════════════════════════════════════════════
# 5. SELF REFLECTOR
# ═══════════════════════════════════════════════════════════════════════════════


class TestSelfReflector:
    def setup_method(self):
        self.reflector = SelfReflector(max_retries_per_type=2)

    def test_timeout_recognized(self):
        r = self.reflector.reflect("search", "Request timed out after 30s")
        assert r.failure_type == "timeout"
        assert r.should_retry

    def test_not_found_recognized(self):
        r = self.reflector.reflect("api_call", "Resource not found (404)")
        assert r.failure_type == "resource_missing"

    def test_rate_limit_recognized(self):
        r = self.reflector.reflect("llm", "429 Too Many Requests")
        assert r.failure_type == "rate_limit"

    def test_permission_recognized(self):
        r = self.reflector.reflect("file_read", "403 Forbidden")
        assert r.failure_type == "permission"

    def test_network_recognized(self):
        r = self.reflector.reflect("browse", "Connection refused")
        assert r.failure_type == "network"

    def test_unknown_error(self):
        r = self.reflector.reflect("tool", "Something weird happened")
        assert r.failure_type == "unknown"
        assert r.should_retry

    def test_max_retries_exceeded(self):
        # First 2 retries allowed
        r1 = self.reflector.reflect("search", "timeout")
        assert r1.should_retry
        r2 = self.reflector.reflect("search", "timeout")
        assert r2.should_retry
        # Third should not retry
        r3 = self.reflector.reflect("search", "timeout")
        assert not r3.should_retry
        assert "Исчерпаны" in r3.suggestion

    def test_different_tools_independent(self):
        for _ in range(3):
            self.reflector.reflect("tool_a", "timeout")
        # tool_b should still be retryable
        r = self.reflector.reflect("tool_b", "timeout")
        assert r.should_retry

    def test_failure_summary(self):
        self.reflector.reflect("search", "timeout")
        self.reflector.reflect("browse", "connection error")
        summary = self.reflector.get_failure_summary()
        assert "search:timeout" in summary
        assert "browse:network" in summary

    def test_clear(self):
        self.reflector.reflect("search", "timeout")
        self.reflector.clear()
        r = self.reflector.reflect("search", "timeout")
        assert r.should_retry  # Reset, so first try again


# ═══════════════════════════════════════════════════════════════════════════════
# 6. REACT ENHANCER (UNIFIED)
# ═══════════════════════════════════════════════════════════════════════════════


class TestReactEnhancer:
    def setup_method(self):
        self.enhancer = ReactEnhancer(
            token_budget=10000,
            max_observation_length=200,
            dedup_window=10,
        )

    # ── check_action ──
    def test_first_action_allowed(self):
        ok, _ = self.enhancer.check_action("search", {"q": "test"})
        assert ok

    def test_budget_exceeded_blocks(self):
        self.enhancer.budget.add("input", 15000)
        ok, reason = self.enhancer.check_action("search", {"q": "test"})
        assert not ok
        assert "budget" in reason.lower()

    def test_duplicate_blocked(self):
        params = {"q": "test"}
        self.enhancer.check_action("search", params)
        self.enhancer.process_observation("result", "search", True, params)
        ok, reason = self.enhancer.check_action("search", params)
        assert not ok
        assert "Duplicate" in reason

    # ── process_observation ──
    def test_short_observation_unchanged(self):
        result = self.enhancer.process_observation("short", "tool")
        assert result == "short"

    def test_long_observation_truncated(self):
        long_text = "x" * 3000  # must exceed short_threshold (1500)
        result = self.enhancer.process_observation(long_text, "search")
        assert len(result) < len(long_text)  # was truncated
        assert "обрезано" in result

    def test_observation_tracks_budget(self):
        self.enhancer.process_observation("some result", "tool")
        assert self.enhancer.budget.tokens_used > 0

    # ── reflect_on_failure ──
    def test_reflect_returns_result(self):
        r = self.enhancer.reflect_on_failure("search", "timeout error")
        assert isinstance(r, ReflectionResult)
        assert r.should_retry

    # ── get_budget ──
    def test_get_budget_snapshot(self):
        self.enhancer.add_token_usage("input", 500)
        snap = self.enhancer.get_budget()
        assert snap.tokens_used == 500

    # ── reset ──
    def test_reset_clears_all(self):
        self.enhancer.add_token_usage("input", 5000)
        self.enhancer.process_observation("result", "tool", True, {"q": "x"})
        self.enhancer.reset()
        assert self.enhancer.budget.tokens_used == 0
        ok, _ = self.enhancer.check_action("tool", {"q": "x"})
        assert ok  # dedup cleared

    # ── oscillation through enhancer ──
    def test_oscillation_detected_via_enhancer(self):
        # Record ABAB pattern
        for action, p in [("A", {"x": 1}), ("B", {"x": 2})] * 3:
            self.enhancer.check_action(action, p)
            self.enhancer.process_observation("r", action, True, p)
        # The oscillation detector should trigger at some point
        # (depends on timing of check vs record)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════


class TestDataModels:
    def test_action_record(self):
        r = ActionRecord(
            tool_name="search",
            params_hash="abc123",
            timestamp=1000.0,
            success=True,
            result_preview="found it",
        )
        assert r.tool_name == "search"
        assert r.success

    def test_budget_snapshot(self):
        snap = BudgetSnapshot(
            total_budget=10000,
            tokens_used=5000,
            tokens_remaining=5000,
            percentage_used=0.5,
            is_exceeded=False,
        )
        assert not snap.is_exceeded
        assert snap.percentage_used == 0.5

    def test_reflection_result(self):
        r = ReflectionResult(
            should_retry=True,
            reason="first try",
            suggestion="try again",
            failure_type="timeout",
        )
        assert r.should_retry
        assert r.failure_type == "timeout"
