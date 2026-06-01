"""
Tests for PDS-Ultimate Evaluation Framework
=============================================
Tests the evaluation framework itself — metrics, runner, evaluators.

Tests cover:
- Metrics calculation (F1, response quality, plan quality, etc.)
- Aggregation (MetricsAggregator)
- Individual evaluators (mode, complexity, sub-agent, etc.)
- Runner (load, filter, run_all, run_single)
- Edge cases and boundary conditions
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from pds_ultimate.tests.eval.metrics import (
    EvalResult,
    LatencyAnalyzer,
    MetricsAggregator,
    MetricsSummary,
    ModeAccuracyMetric,
    PlanQualityMetric,
    ResponseQualityMetric,
    SubAgentClassificationMetric,
    ToolSelectionMetric,
)
from pds_ultimate.tests.eval.runner import (
    AnswerSanitizeEvaluator,
    BlocklistEvaluator,
    ComplexityEvaluator,
    EvalRunner,
    F1MetricEvaluator,
    LLMComplexityEvaluator,
    ModeSelectionEvaluator,
    OscillationEvaluator,
    ParamValidationEvaluator,
    PlanQualityEvaluator,
    RateLimitEvaluator,
    ResponseQualityEvaluator,
    SelfAttentionEvaluator,
    SubAgentEvaluator,
    TaskVerifierEvaluator,
    filter_cases,
    load_test_cases,
)

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1: Metric Calculators
# ═══════════════════════════════════════════════════════════════════════════


class TestModeAccuracyMetric:
    def test_correct_mode(self):
        r = ModeAccuracyMetric.evaluate("simple", "simple")
        assert r.passed is True
        assert r.score == 1.0

    def test_incorrect_mode(self):
        r = ModeAccuracyMetric.evaluate("simple", "tool_loop")
        assert r.passed is False
        assert r.score == 0.0

    def test_all_modes(self):
        for mode in ("simple", "tool_loop", "planned"):
            r = ModeAccuracyMetric.evaluate(mode, mode)
            assert r.passed is True


class TestToolSelectionMetric:
    def test_perfect_match(self):
        assert ToolSelectionMetric.f1({"a", "b"}, {"a", "b"}) == 1.0

    def test_no_match(self):
        assert ToolSelectionMetric.f1({"a"}, {"b"}) == 0.0

    def test_partial_precision(self):
        p = ToolSelectionMetric.precision({"a"}, {"a", "b"})
        assert p == 0.5

    def test_partial_recall(self):
        r = ToolSelectionMetric.recall({"a", "b"}, {"a"})
        assert r == 0.5

    def test_f1_partial(self):
        f1 = ToolSelectionMetric.f1({"a", "b"}, {"a"})
        expected = 2 * 1.0 * 0.5 / (1.0 + 0.5)  # P=1, R=0.5
        assert abs(f1 - expected) < 0.01

    def test_both_empty(self):
        assert ToolSelectionMetric.f1(set(), set()) == 1.0

    def test_expected_empty_actual_not(self):
        assert ToolSelectionMetric.f1(set(), {"a"}) == 0.0

    def test_evaluate_returns_eval_result(self):
        r = ToolSelectionMetric.evaluate(["a", "b"], ["a", "b"])
        assert isinstance(r, EvalResult)
        assert r.score == 1.0
        assert r.passed is True

    def test_evaluate_failing(self):
        r = ToolSelectionMetric.evaluate(["a"], ["b", "c"])
        assert r.score == 0.0
        assert r.passed is False


class TestResponseQualityMetric:
    def test_good_answer(self):
        r = ResponseQualityMetric.evaluate("Привет", "Привет! Как дела?")
        assert r.score >= 0.7
        assert r.passed is True

    def test_empty_answer(self):
        r = ResponseQualityMetric.evaluate("Привет", "")
        assert r.score == 0.0
        assert r.passed is False

    def test_json_leak(self):
        r = ResponseQualityMetric.evaluate(
            "Что?",
            '{"action": "tool_call", "name": "search"}',
        )
        assert r.score < 0.85  # penalty applied but other criteria still score

    def test_hallucination_marker(self):
        r = ResponseQualityMetric.evaluate(
            "Помоги",
            "К сожалению, я не могу помочь вам.",
        )
        assert r.score <= 0.75  # penalty applied

    def test_repetitive_answer(self):
        r = ResponseQualityMetric.evaluate(
            "Привет",
            "Ок. Ок. Ок. Ок. Ок. Ок. Ок. Ок.",
        )
        assert r.score <= 0.75  # repetition penalty applied

    def test_too_brief_for_complex(self):
        r = ResponseQualityMetric.evaluate(
            "Расскажи подробно о машинном обучении и глубоком обучении",
            "Ок",
        )
        assert r.score < 0.7  # brief penalty applied


class TestSubAgentClassificationMetric:
    def test_match(self):
        r = SubAgentClassificationMetric.evaluate("research", "research")
        assert r.passed is True
        assert r.score == 1.0

    def test_mismatch(self):
        r = SubAgentClassificationMetric.evaluate("research", "creative")
        assert r.passed is False
        assert r.score == 0.0


class TestPlanQualityMetric:
    def test_good_plan(self):
        plan = {
            "nodes": {
                "s1": {"description": "A", "depends_on": []},
                "s2": {"description": "B", "depends_on": []},
                "s3": {"description": "C", "depends_on": ["s1", "s2"]},
                "synthesize": {"description": "Done", "depends_on": ["s3"]},
            },
        }
        r = PlanQualityMetric.evaluate(plan)
        assert r.score >= 0.8
        assert r.passed is True

    def test_single_node(self):
        plan = {"nodes": {"s1": {"description": "A", "depends_on": []}}}
        r = PlanQualityMetric.evaluate(plan)
        assert r.score < 0.5

    def test_orphan_deps(self):
        plan = {
            "nodes": {
                "s1": {"description": "A", "depends_on": ["missing"]},
                "synthesize": {"description": "Done", "depends_on": ["s1"]},
            },
        }
        r = PlanQualityMetric.evaluate(plan)
        assert r.score < 0.8

    def test_empty_plan(self):
        r = PlanQualityMetric.evaluate({"nodes": {}})
        assert r.score == 0.0
        assert r.passed is False

    def test_no_synthesize(self):
        plan = {
            "nodes": {
                "s1": {"description": "A", "depends_on": []},
                "s2": {"description": "B", "depends_on": []},
            },
        }
        r = PlanQualityMetric.evaluate(plan)
        # Has 2 nodes, parallel, no orphans, but no synthesize
        assert r.score < 1.0


class TestLatencyAnalyzer:
    def test_empty(self):
        result = LatencyAnalyzer.analyze([])
        assert result["p50"] == 0.0

    def test_single(self):
        results = [EvalResult(case_id="1", category="x",
                              passed=True, score=1.0, latency_ms=100)]
        lat = LatencyAnalyzer.analyze(results)
        assert lat["p50"] == 100
        assert lat["mean"] == 100

    def test_multiple(self):
        results = [
            EvalResult(case_id=str(i), category="x",
                       passed=True, score=1.0, latency_ms=i * 10)
            for i in range(1, 11)
        ]
        lat = LatencyAnalyzer.analyze(results)
        assert lat["p50"] > 0
        assert lat["max"] == 100


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2: Metrics Aggregator
# ═══════════════════════════════════════════════════════════════════════════


class TestMetricsAggregator:
    def test_empty(self):
        s = MetricsAggregator.aggregate([])
        assert s.total_cases == 0
        assert s.overall_score == 0.0

    def test_all_passed(self):
        results = [
            EvalResult(
                case_id=f"t{i}", category="mode_selection", passed=True, score=1.0)
            for i in range(10)
        ]
        s = MetricsAggregator.aggregate(results)
        assert s.total_cases == 10
        assert s.passed == 10
        assert s.pass_rate == 1.0

    def test_mixed(self):
        results = [
            EvalResult(case_id="t1", category="mode_selection",
                       passed=True, score=1.0),
            EvalResult(case_id="t2", category="mode_selection",
                       passed=False, score=0.0),
        ]
        s = MetricsAggregator.aggregate(results)
        assert s.total_cases == 2
        assert s.passed == 1
        assert s.failed == 1
        assert s.mode_accuracy == 0.5

    def test_multi_category(self):
        results = [
            EvalResult(case_id="t1", category="mode_selection",
                       passed=True, score=1.0),
            EvalResult(case_id="t2", category="tool_selection",
                       passed=True, score=0.8),
            EvalResult(case_id="t3", category="response_quality",
                       passed=True, score=0.7),
        ]
        s = MetricsAggregator.aggregate(results)
        assert len(s.category_scores) == 3
        assert s.mode_accuracy == 1.0
        assert s.tool_selection_f1 == 0.8
        assert s.response_quality == 0.7

    def test_format_report(self):
        results = [
            EvalResult(case_id="t1", category="mode_selection", passed=True, score=1.0,
                       latency_ms=50),
        ]
        s = MetricsAggregator.aggregate(results)
        report = MetricsAggregator.format_report(s)
        assert "OVERALL SCORE" in report
        assert "Mode Accuracy" in report

    def test_pass_rate_property(self):
        s = MetricsSummary(total_cases=4, passed=3, failed=1)
        assert s.pass_rate == 0.75


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3: Test Case Loading
# ═══════════════════════════════════════════════════════════════════════════


class TestLoadTestCases:
    def test_load_from_default_path(self):
        cases = load_test_cases()
        assert len(cases) >= 100  # 100+ test cases required

    def test_load_custom_path(self):
        data = {
            "test_cases": [
                {"id": "test_1", "category": "mode_selection"},
            ],
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        ) as f:
            json.dump(data, f)
            f.flush()
            cases = load_test_cases(Path(f.name))
        assert len(cases) == 1
        assert cases[0]["id"] == "test_1"

    def test_filter_by_category(self):
        cases = load_test_cases()
        mode_cases = filter_cases(cases, category="mode_selection")
        assert len(mode_cases) >= 10
        assert all(c["category"] == "mode_selection" for c in mode_cases)

    def test_filter_by_ids(self):
        cases = load_test_cases()
        filtered = filter_cases(cases, ids=["mode_01", "mode_02"])
        assert len(filtered) == 2

    def test_filter_combined(self):
        cases = load_test_cases()
        filtered = filter_cases(
            cases, category="mode_selection", ids=["mode_01"])
        assert len(filtered) == 1
        assert filtered[0]["id"] == "mode_01"

    def test_all_cases_have_id_and_category(self):
        cases = load_test_cases()
        for case in cases:
            assert "id" in case, f"Case missing id: {case}"
            assert "category" in case, f"Case {case['id']} missing category"


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4: Individual Evaluators
# ═══════════════════════════════════════════════════════════════════════════


class TestModeSelectionEvaluator:
    def test_simple_greeting(self):
        case = {"id": "t1", "input": "Привет", "expected_mode": "simple"}
        r = ModeSelectionEvaluator().evaluate(case)
        assert r.passed is True
        assert r.score == 1.0

    def test_complex_request(self):
        case = {
            "id": "t2",
            "input": "Проанализируй и сравни продажи за 3 месяца, создай отчёт по шагам",
            "expected_mode": "planned",
        }
        r = ModeSelectionEvaluator().evaluate(case)
        assert r.passed is True

    def test_has_latency(self):
        case = {"id": "t3", "input": "Ок", "expected_mode": "simple"}
        r = ModeSelectionEvaluator().evaluate(case)
        assert r.latency_ms >= 0


class TestComplexityEvaluator:
    def test_simple(self):
        case = {
            "id": "c1",
            "input": "Привет",
            "expected_planner_complexity": "simple",
        }
        r = ComplexityEvaluator().evaluate(case)
        assert r.passed is True

    def test_complex(self):
        case = {
            "id": "c2",
            "input": "Проанализируй и сравни продажи за 3 месяца создай отчёт по шагам",
            "expected_planner_complexity": "complex",
        }
        r = ComplexityEvaluator().evaluate(case)
        assert r.passed is True

    def test_moderate(self):
        case = {
            "id": "c3",
            "input": "Первое предложение. Второе предложение. Третье предложение. Четвертое.",
            "expected_planner_complexity": "moderate",
        }
        r = ComplexityEvaluator().evaluate(case)
        assert r.passed is True


class TestLLMComplexityEvaluator:
    def test_simple(self):
        case = {"id": "l1", "input": "Привет", "expected_complexity": "simple"}
        r = LLMComplexityEvaluator().evaluate(case)
        assert r.passed is True

    def test_complex(self):
        case = {"id": "l2", "input": "Проанализируй рынок",
                "expected_complexity": "complex"}
        r = LLMComplexityEvaluator().evaluate(case)
        assert r.passed is True

    def test_reasoning(self):
        case = {"id": "l3", "input": "Глубокий анализ конкурентов",
                "expected_complexity": "reasoning"}
        r = LLMComplexityEvaluator().evaluate(case)
        assert r.passed is True


class TestSubAgentEvaluator:
    def test_tool_type(self):
        case = {
            "id": "sa1",
            "node_description": "Выполни create_order",
            "node_tool_name": "create_order",
            "expected_type": "tool",
        }
        r = SubAgentEvaluator().evaluate(case)
        assert r.passed is True

    def test_research_type(self):
        case = {
            "id": "sa2",
            "node_description": "Найди информацию о курсе доллара",
            "node_tool_name": None,
            "expected_type": "research",
        }
        r = SubAgentEvaluator().evaluate(case)
        assert r.passed is True

    def test_analysis_type(self):
        case = {
            "id": "sa3",
            "node_description": "Рассчитай процент прибыли",
            "node_tool_name": None,
            "expected_type": "analysis",
        }
        r = SubAgentEvaluator().evaluate(case)
        assert r.passed is True

    def test_creative_type(self):
        case = {
            "id": "sa4",
            "node_description": "Напиши отчёт о продажах",
            "node_tool_name": None,
            "expected_type": "creative",
        }
        r = SubAgentEvaluator().evaluate(case)
        assert r.passed is True

    def test_generic_type(self):
        case = {
            "id": "sa5",
            "node_description": "Сделай что-то",
            "node_tool_name": None,
            "expected_type": "generic",
        }
        r = SubAgentEvaluator().evaluate(case)
        assert r.passed is True


class TestResponseQualityEvaluator:
    def test_good_answer(self):
        case = {
            "id": "rq1",
            "query": "Привет",
            "answer": "Привет! Как дела?",
            "min_score": 0.7,
        }
        r = ResponseQualityEvaluator().evaluate(case)
        assert r.passed is True

    def test_empty_answer(self):
        case = {
            "id": "rq2",
            "query": "Расскажи о Python",
            "answer": "",
            "min_score": 0.0,
            "max_score": 0.1,
        }
        r = ResponseQualityEvaluator().evaluate(case)
        assert r.passed is True  # score 0.0 is within [0.0, 0.1]


class TestTaskVerifierEvaluator:
    def test_good_result(self):
        case = {
            "id": "tv1",
            "task": "Привет",
            "result": "Привет! Рад тебя видеть!",
            "min_score": 0.5,
        }
        r = TaskVerifierEvaluator().evaluate(case)
        assert r.passed is True

    def test_empty_result(self):
        case = {
            "id": "tv2",
            "task": "Помоги",
            "result": "",
            "min_score": 0.0,
            "max_score": 0.2,
        }
        r = TaskVerifierEvaluator().evaluate(case)
        assert r.passed is True

    def test_json_leak(self):
        case = {
            "id": "tv3",
            "task": "Расскажи",
            "result": '{"action": "tool_call", "name": "search", "params": {}}',
            "min_score": 0.0,
            "max_score": 0.4,
        }
        r = TaskVerifierEvaluator().evaluate(case)
        assert r.passed is True


class TestPlanQualityEvaluator:
    def test_good_plan(self):
        case = {
            "id": "pq1",
            "plan": {
                "nodes": {
                    "s1": {"description": "A", "depends_on": []},
                    "s2": {"description": "B", "depends_on": []},
                    "s3": {"description": "C", "depends_on": ["s1", "s2"]},
                    "synthesize": {"description": "Done", "depends_on": ["s3"]},
                },
            },
            "min_score": 0.8,
        }
        r = PlanQualityEvaluator().evaluate(case)
        assert r.passed is True


class TestF1MetricEvaluator:
    def test_perfect(self):
        case = {
            "id": "f1",
            "expected_tools": ["a", "b"],
            "actual_tools": ["a", "b"],
            "expected_f1": 1.0,
        }
        r = F1MetricEvaluator().evaluate(case)
        assert r.passed is True

    def test_zero(self):
        case = {
            "id": "f2",
            "expected_tools": ["a"],
            "actual_tools": ["b"],
            "expected_f1": 0.0,
        }
        r = F1MetricEvaluator().evaluate(case)
        assert r.passed is True

    def test_range(self):
        case = {
            "id": "f3",
            "expected_tools": ["a", "b"],
            "actual_tools": ["a"],
            "expected_f1_min": 0.6,
            "expected_f1_max": 0.7,
        }
        r = F1MetricEvaluator().evaluate(case)
        assert r.passed is True


class TestSelfAttentionEvaluator:
    def test_relevant(self):
        case = {
            "id": "sa1",
            "goal": "Найди курс доллара",
            "result": "Курс доллара: 1 USD = 19.5 TMT",
            "min_score": 0.3,
        }
        r = SelfAttentionEvaluator().evaluate(case)
        assert r.passed is True

    def test_empty_result(self):
        case = {
            "id": "sa2",
            "goal": "Создай заказ",
            "result": "",
            "expected_score": 0.0,
        }
        r = SelfAttentionEvaluator().evaluate(case)
        assert r.passed is True


class TestOscillationEvaluator:
    def test_abab_detected(self):
        case = {
            "id": "o1",
            "steps": [
                {"action_type": "tool_call", "tool_name": "search"},
                {"action_type": "tool_call", "tool_name": "translate"},
                {"action_type": "tool_call", "tool_name": "search"},
                {"action_type": "tool_call", "tool_name": "translate"},
            ],
            "expected_oscillation": True,
        }
        r = OscillationEvaluator().evaluate(case)
        assert r.passed is True

    def test_no_oscillation(self):
        case = {
            "id": "o2",
            "steps": [
                {"action_type": "tool_call", "tool_name": "a"},
                {"action_type": "tool_call", "tool_name": "b"},
                {"action_type": "tool_call", "tool_name": "c"},
                {"action_type": "tool_call", "tool_name": "d"},
            ],
            "expected_oscillation": False,
        }
        r = OscillationEvaluator().evaluate(case)
        assert r.passed is True


class TestAnswerSanitizeEvaluator:
    def test_think_tags(self):
        case = {
            "id": "as1",
            "input": "<think>thinking</think>Ответ",
            "expected_contains": "Ответ",
            "expected_not_contains": "<think>",
        }
        r = AnswerSanitizeEvaluator().evaluate(case)
        assert r.passed is True

    def test_json_extract(self):
        case = {
            "id": "as2",
            "input": '{"answer": "Готово!"}',
            "expected_result": "Готово!",
        }
        r = AnswerSanitizeEvaluator().evaluate(case)
        assert r.passed is True

    def test_plain_text(self):
        case = {
            "id": "as3",
            "input": "Простой текст",
            "expected_result": "Простой текст",
        }
        r = AnswerSanitizeEvaluator().evaluate(case)
        assert r.passed is True

    def test_empty(self):
        case = {
            "id": "as4",
            "input": "",
            "expected_result": "",
        }
        r = AnswerSanitizeEvaluator().evaluate(case)
        assert r.passed is True


class TestRateLimitEvaluator:
    def test_blocks_over_limit(self):
        case = {
            "id": "rl1",
            "tool_name": "fast_tool",
            "limit": 3,
            "calls": 5,
            "expected_blocked_after": 3,
        }
        r = RateLimitEvaluator().evaluate(case)
        assert r.passed is True

    def test_no_blocking(self):
        case = {
            "id": "rl2",
            "tool_name": "normal_tool",
            "limit": 100,
            "calls": 50,
            "expected_blocked_after": -1,
        }
        r = RateLimitEvaluator().evaluate(case)
        assert r.passed is True


class TestBlocklistEvaluator:
    def test_blocked(self):
        case = {
            "id": "bl1",
            "blocked_tools": ["dangerous_tool"],
            "test_tool": "dangerous_tool",
            "expected_blocked": True,
        }
        r = BlocklistEvaluator().evaluate(case)
        assert r.passed is True

    def test_not_blocked(self):
        case = {
            "id": "bl2",
            "blocked_tools": ["dangerous_tool"],
            "test_tool": "safe_tool",
            "expected_blocked": False,
        }
        r = BlocklistEvaluator().evaluate(case)
        assert r.passed is True


class TestParamValidationEvaluator:
    def test_valid(self):
        case = {
            "id": "pv1",
            "schema": [{"name": "query", "param_type": "string", "required": True}],
            "params": {"query": "test"},
            "expected_valid": True,
        }
        r = ParamValidationEvaluator().evaluate(case)
        assert r.passed is True

    def test_missing_required(self):
        case = {
            "id": "pv2",
            "schema": [{"name": "query", "param_type": "string", "required": True}],
            "params": {},
            "expected_valid": False,
        }
        r = ParamValidationEvaluator().evaluate(case)
        assert r.passed is True

    def test_number_coercion(self):
        case = {
            "id": "pv3",
            "schema": [{"name": "count", "param_type": "number", "required": True}],
            "params": {"count": "42"},
            "expected_valid": True,
        }
        r = ParamValidationEvaluator().evaluate(case)
        assert r.passed is True


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 5: EvalRunner Integration
# ═══════════════════════════════════════════════════════════════════════════


class TestEvalRunner:
    def test_total_cases(self):
        runner = EvalRunner()
        assert runner.total_cases >= 100

    def test_get_categories(self):
        runner = EvalRunner()
        cats = runner.get_categories()
        assert "mode_selection" in cats
        assert "complexity_classification" in cats
        assert "sub_agent_classification" in cats

    def test_run_all(self):
        runner = EvalRunner()
        summary = runner.run_all()
        assert summary.total_cases > 0
        assert summary.passed > 0
        assert summary.overall_score > 0

    def test_run_by_category(self):
        runner = EvalRunner()
        summary = runner.run_all(category="mode_selection")
        assert summary.total_cases >= 10
        assert "mode_selection" in summary.category_scores

    def test_run_single(self):
        runner = EvalRunner()
        result = runner.run_single("mode_01")
        assert result is not None
        assert result.case_id == "mode_01"

    def test_run_single_nonexistent(self):
        runner = EvalRunner()
        result = runner.run_single("nonexistent_999")
        assert result is None

    def test_format_report(self):
        runner = EvalRunner()
        summary = runner.run_all(category="f1_metric")
        report = runner.format_report(summary)
        assert isinstance(report, str)
        assert "OVERALL SCORE" in report

    def test_all_golden_cases_pass(self):
        """All golden test cases in test_cases.json should pass."""
        runner = EvalRunner()
        summary = runner.run_all()
        # Allow up to 10% failure rate for edge cases
        assert summary.pass_rate >= 0.90, (
            f"Pass rate {summary.pass_rate:.2%} below 90% threshold. "
            f"Failed: {summary.failed}/{summary.total_cases}"
        )

    def test_overall_score_above_threshold(self):
        """Overall score should be above 0.7 (agent quality bar)."""
        runner = EvalRunner()
        summary = runner.run_all()
        assert summary.overall_score >= 0.7, (
            f"Overall score {summary.overall_score:.2f} below 0.70 threshold"
        )

    def test_mode_accuracy_above_threshold(self):
        """Mode accuracy should be high — routing is critical."""
        runner = EvalRunner()
        summary = runner.run_all(category="mode_selection")
        assert summary.mode_accuracy >= 0.8, (
            f"Mode accuracy {summary.mode_accuracy:.2f} below 0.80 threshold"
        )

    def test_run_custom_cases(self):
        """Test with custom JSON file."""
        data = {
            "test_cases": [
                {
                    "id": "custom_01",
                    "category": "f1_metric",
                    "expected_tools": ["a"],
                    "actual_tools": ["a"],
                    "expected_f1": 1.0,
                },
            ],
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        ) as f:
            json.dump(data, f)
            f.flush()
            runner = EvalRunner(cases_path=Path(f.name))
            summary = runner.run_all()
        assert summary.total_cases == 1
        assert summary.passed == 1
