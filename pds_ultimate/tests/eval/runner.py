"""
PDS-Ultimate Evaluation Runner
================================
Offline evaluation runner that executes test cases against the agent
components without needing a live LLM connection.

Evaluates:
1. Mode selection accuracy (Agent._select_mode)
2. Planner complexity classification (TaskPlanner.classify_complexity)
3. LLM complexity analysis (TaskComplexityAnalyzer.analyze)
4. Sub-agent type classification (SubAgentFactory.classify)
5. Response quality heuristics (TaskVerifier.fast_check)
6. Answer sanitization (_sanitize_answer)
7. Oscillation detection (Agent._detect_oscillation)
8. Self-attention scoring (SelfAttentionScorer.score)
9. Plan quality evaluation (PlanQualityMetric.evaluate)
10. Tool selection F1 calculation (ToolSelectionMetric.f1)
11. Rate limiting behavior (ToolRateLimiter)
12. Tool blocklist (ToolBlocklist)
13. Parameter validation (ParameterValidator)

Usage:
    from pds_ultimate.tests.eval.runner import EvalRunner
    runner = EvalRunner()
    summary = runner.run_all()
    print(runner.format_report(summary))
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from pds_ultimate.tests.eval.metrics import (
    EvalResult,
    MetricsAggregator,
    MetricsSummary,
    ModeAccuracyMetric,
    PlanQualityMetric,
    ResponseQualityMetric,
    SubAgentClassificationMetric,
    ToolSelectionMetric,
)

# Test cases file
_CASES_PATH = Path(__file__).parent / "test_cases.json"


# ─── Test Case Loader ───────────────────────────────────────────────────────

def load_test_cases(path: Path | None = None) -> list[dict]:
    """Load test cases from JSON file."""
    p = path or _CASES_PATH
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("test_cases", [])


def filter_cases(
    cases: list[dict],
    category: str | None = None,
    ids: list[str] | None = None,
) -> list[dict]:
    """Filter test cases by category or ids."""
    result = cases
    if category:
        result = [c for c in result if c.get("category") == category]
    if ids:
        id_set = set(ids)
        result = [c for c in result if c.get("id") in id_set]
    return result


# ─── Individual Evaluators ──────────────────────────────────────────────────

class ModeSelectionEvaluator:
    """
    Evaluates mode selection by running Agent._select_mode logic
    WITHOUT instantiating a real Agent (we replicate the logic).
    """

    def evaluate(self, case: dict) -> EvalResult:
        """Evaluate a mode_selection test case."""
        from pds_ultimate.core.llm_engine import TaskComplexityAnalyzer
        from pds_ultimate.core.planner import PlanComplexity, task_planner

        message = case["input"]
        expected = case["expected_mode"]
        start = time.time()

        # Replicate Agent._select_mode logic
        planner_complexity = task_planner.classify_complexity(message)
        llm_complexity = TaskComplexityAnalyzer.analyze(message)

        # Both say simple → simple mode
        if planner_complexity == PlanComplexity.SIMPLE and llm_complexity == "simple":
            actual = "simple"
        elif planner_complexity == PlanComplexity.COMPLEX:
            actual = "planned"
        else:
            actual = "tool_loop"

        elapsed = (time.time() - start) * 1000
        result = ModeAccuracyMetric.evaluate(expected, actual)
        result.case_id = case["id"]
        result.latency_ms = elapsed
        return result


class ComplexityEvaluator:
    """Evaluates TaskPlanner.classify_complexity."""

    def evaluate(self, case: dict) -> EvalResult:
        from pds_ultimate.core.planner import task_planner

        message = case["input"]
        expected = case["expected_planner_complexity"]
        start = time.time()

        actual = task_planner.classify_complexity(message).value
        elapsed = (time.time() - start) * 1000

        match = expected == actual
        return EvalResult(
            case_id=case["id"],
            category="complexity_classification",
            passed=match,
            score=1.0 if match else 0.0,
            expected=expected,
            actual=actual,
            latency_ms=elapsed,
            details=f"Expected '{expected}', got '{actual}'"
            if not match else "Matched",
        )


class LLMComplexityEvaluator:
    """Evaluates TaskComplexityAnalyzer.analyze."""

    def evaluate(self, case: dict) -> EvalResult:
        from pds_ultimate.core.llm_engine import TaskComplexityAnalyzer

        message = case["input"]
        expected = case["expected_complexity"]
        start = time.time()

        actual = TaskComplexityAnalyzer.analyze(message).value
        elapsed = (time.time() - start) * 1000

        match = expected == actual
        return EvalResult(
            case_id=case["id"],
            category="llm_complexity",
            passed=match,
            score=1.0 if match else 0.0,
            expected=expected,
            actual=actual,
            latency_ms=elapsed,
            details=f"Expected '{expected}', got '{actual}'"
            if not match else "Matched",
        )


class SubAgentEvaluator:
    """Evaluates SubAgentFactory.classify."""

    def evaluate(self, case: dict) -> EvalResult:
        from pds_ultimate.core.planner import PlanNode
        from pds_ultimate.core.sub_agents import SubAgentFactory

        node = PlanNode(
            id="eval_node",
            description=case["node_description"],
            tool_name=case.get("node_tool_name"),
        )
        expected = case["expected_type"]
        start = time.time()

        actual = SubAgentFactory.classify(node).value
        elapsed = (time.time() - start) * 1000

        result = SubAgentClassificationMetric.evaluate(expected, actual)
        result.case_id = case["id"]
        result.latency_ms = elapsed
        return result


class ResponseQualityEvaluator:
    """Evaluates ResponseQualityMetric against golden answers."""

    def evaluate(self, case: dict) -> EvalResult:
        query = case["query"]
        answer = case["answer"]
        start = time.time()

        result = ResponseQualityMetric.evaluate(query, answer)
        elapsed = (time.time() - start) * 1000

        result.case_id = case["id"]
        result.latency_ms = elapsed

        # Check against golden bounds
        min_score = case.get("min_score", 0.0)
        max_score = case.get("max_score", 1.0)
        result.passed = min_score <= result.score <= max_score
        if not result.passed:
            result.details += (
                f" | Score {result.score:.2f} outside [{min_score:.2f}, {max_score:.2f}]"
            )

        return result


class TaskVerifierEvaluator:
    """Evaluates TaskVerifier.fast_check."""

    def evaluate(self, case: dict) -> EvalResult:
        from pds_ultimate.core.agent import TaskVerifier

        task = case["task"]
        result_text = case["result"]
        start = time.time()

        score = TaskVerifier.fast_check(task, result_text)
        elapsed = (time.time() - start) * 1000

        min_score = case.get("min_score", 0.0)
        max_score = case.get("max_score", 1.0)
        passed = min_score <= score <= max_score

        return EvalResult(
            case_id=case["id"],
            category="task_verifier",
            passed=passed,
            score=score,
            expected=f"[{min_score}, {max_score}]",
            actual=score,
            latency_ms=elapsed,
            details=f"Score={score:.2f}, range=[{min_score:.2f}, {max_score:.2f}]"
            + ("" if passed else " — OUTSIDE RANGE"),
        )


class PlanQualityEvaluator:
    """Evaluates plan quality."""

    def evaluate(self, case: dict) -> EvalResult:
        plan_dict = case["plan"]
        start = time.time()

        result = PlanQualityMetric.evaluate(plan_dict)
        elapsed = (time.time() - start) * 1000

        result.case_id = case["id"]
        result.latency_ms = elapsed

        min_score = case.get("min_score", 0.0)
        max_score = case.get("max_score", 1.0)
        result.passed = min_score <= result.score <= max_score
        if not result.passed:
            result.details += (
                f" | Score {result.score:.2f} outside [{min_score:.2f}, {max_score:.2f}]"
            )

        return result


class F1MetricEvaluator:
    """Evaluates ToolSelectionMetric.f1 calculation."""

    def evaluate(self, case: dict) -> EvalResult:
        expected_tools = case["expected_tools"]
        actual_tools = case["actual_tools"]
        start = time.time()

        f1 = ToolSelectionMetric.f1(set(expected_tools), set(actual_tools))
        elapsed = (time.time() - start) * 1000

        # Check exact or range
        if "expected_f1" in case:
            target = case["expected_f1"]
            passed = abs(f1 - target) < 0.01
            details = f"F1={f1:.3f}, expected={target:.3f}"
        else:
            f1_min = case.get("expected_f1_min", 0.0)
            f1_max = case.get("expected_f1_max", 1.0)
            passed = f1_min <= f1 <= f1_max
            details = f"F1={f1:.3f}, range=[{f1_min:.3f}, {f1_max:.3f}]"

        return EvalResult(
            case_id=case["id"],
            category="f1_metric",
            passed=passed,
            score=f1,
            latency_ms=elapsed,
            details=details,
        )


class SelfAttentionEvaluator:
    """Evaluates SelfAttentionScorer.score."""

    def evaluate(self, case: dict) -> EvalResult:
        from pds_ultimate.core.sub_agents import SelfAttentionScorer

        goal = case["goal"]
        result_text = case["result"]
        start = time.time()

        score = SelfAttentionScorer.score(goal, result_text)
        elapsed = (time.time() - start) * 1000

        # Check bounds
        if "expected_score" in case:
            target = case["expected_score"]
            passed = abs(score - target) < 0.05
            details = f"Score={score:.3f}, expected={target:.3f}"
        else:
            min_score = case.get("min_score", 0.0)
            max_score = case.get("max_score", 1.0)
            passed = min_score <= score <= max_score
            details = f"Score={score:.3f}, range=[{min_score:.3f}, {max_score:.3f}]"

        return EvalResult(
            case_id=case["id"],
            category="self_attention",
            passed=passed,
            score=score,
            latency_ms=elapsed,
            details=details,
        )


class OscillationEvaluator:
    """Evaluates Agent._detect_oscillation."""

    def evaluate(self, case: dict) -> EvalResult:
        from pds_ultimate.core.agent import Agent, AgentAction, AgentStep

        agent = Agent.__new__(Agent)
        agent.OSCILLATION_WINDOW = 4

        steps = []
        for s in case["steps"]:
            action = AgentAction(
                action_type=s["action_type"],
                tool_name=s.get("tool_name"),
            )
            steps.append(AgentStep(iteration=len(steps) + 1, action=action))

        start = time.time()
        detected = agent._detect_oscillation(steps)
        elapsed = (time.time() - start) * 1000

        expected = case["expected_oscillation"]
        passed = detected == expected

        return EvalResult(
            case_id=case["id"],
            category="oscillation",
            passed=passed,
            score=1.0 if passed else 0.0,
            expected=expected,
            actual=detected,
            latency_ms=elapsed,
            details=f"Expected oscillation={expected}, got={detected}",
        )


class AnswerSanitizeEvaluator:
    """Evaluates _sanitize_answer."""

    def evaluate(self, case: dict) -> EvalResult:
        from pds_ultimate.core.agent import _sanitize_answer

        text = case["input"]
        start = time.time()
        result = _sanitize_answer(text)
        elapsed = (time.time() - start) * 1000

        passed = True
        details = []

        if "expected_result" in case:
            if result != case["expected_result"]:
                passed = False
                details.append(
                    f"Expected '{case['expected_result']}', got '{result}'")

        if "expected_contains" in case:
            if case["expected_contains"] not in result:
                passed = False
                details.append(f"Missing '{case['expected_contains']}'")

        if "expected_not_contains" in case:
            if case["expected_not_contains"] in result:
                passed = False
                details.append(
                    f"Should not contain '{case['expected_not_contains']}'")

        return EvalResult(
            case_id=case["id"],
            category="answer_sanitize",
            passed=passed,
            score=1.0 if passed else 0.0,
            latency_ms=elapsed,
            details="; ".join(details) if details else "OK",
        )


class RateLimitEvaluator:
    """Evaluates ToolRateLimiter behavior."""

    def evaluate(self, case: dict) -> EvalResult:
        from pds_ultimate.core.tool_audit import ToolRateLimiter

        limiter = ToolRateLimiter()
        tool_name = case["tool_name"]
        limit = case["limit"]
        calls = case["calls"]
        expected_blocked_after = case["expected_blocked_after"]

        limiter.set_limit(tool_name, limit)
        start = time.time()

        blocked_at = -1
        for i in range(calls):
            if not limiter.check(tool_name):
                blocked_at = i
                break
            limiter.record(tool_name)

        elapsed = (time.time() - start) * 1000

        if expected_blocked_after == -1:
            passed = blocked_at == -1
        else:
            passed = blocked_at == expected_blocked_after

        return EvalResult(
            case_id=case["id"],
            category="rate_limiting",
            passed=passed,
            score=1.0 if passed else 0.0,
            expected=expected_blocked_after,
            actual=blocked_at,
            latency_ms=elapsed,
            details=f"Blocked at call #{blocked_at}, expected #{expected_blocked_after}",
        )


class BlocklistEvaluator:
    """Evaluates ToolBlocklist behavior."""

    def evaluate(self, case: dict) -> EvalResult:
        from pds_ultimate.core.tool_sandbox import ToolBlocklist

        blocklist = ToolBlocklist()
        for tool_name in case["blocked_tools"]:
            blocklist.block(tool_name)

        start = time.time()
        is_blocked = blocklist.is_blocked(case["test_tool"])
        elapsed = (time.time() - start) * 1000

        expected = case["expected_blocked"]
        passed = is_blocked == expected

        return EvalResult(
            case_id=case["id"],
            category="tool_blocklist",
            passed=passed,
            score=1.0 if passed else 0.0,
            expected=expected,
            actual=is_blocked,
            latency_ms=elapsed,
            details=f"Tool '{case['test_tool']}' blocked={is_blocked}, expected={expected}",
        )


class ParamValidationEvaluator:
    """Evaluates ParameterValidator behavior."""

    def evaluate(self, case: dict) -> EvalResult:
        from pds_ultimate.core.tool_sandbox import ParameterValidator
        from pds_ultimate.core.tools import Tool, ToolParameter

        # Build tool with schema
        params = [
            ToolParameter(
                name=p["name"],
                param_type=p["param_type"],
                description="",
                required=p.get("required", True),
            )
            for p in case["schema"]
        ]
        tool = Tool(name="test_tool", description="Test", parameters=params)

        validator = ParameterValidator()
        start = time.time()
        try:
            cleaned = validator.validate(case["params"], tool.parameters)
            is_valid = True
            errors = []
        except Exception as e:
            is_valid = False
            errors = [str(e)]
            cleaned = {}
        elapsed = (time.time() - start) * 1000

        expected = case["expected_valid"]
        passed = is_valid == expected

        return EvalResult(
            case_id=case["id"],
            category="param_validation",
            passed=passed,
            score=1.0 if passed else 0.0,
            expected=expected,
            actual=is_valid,
            latency_ms=elapsed,
            details=f"Valid={is_valid}, expected={expected}, errors={errors}",
        )


# ─── Category → Evaluator mapping ──────────────────────────────────────────

_EVALUATORS: dict[str, Any] = {
    "mode_selection": ModeSelectionEvaluator,
    "complexity_classification": ComplexityEvaluator,
    "llm_complexity": LLMComplexityEvaluator,
    "sub_agent_classification": SubAgentEvaluator,
    "response_quality": ResponseQualityEvaluator,
    "task_verifier": TaskVerifierEvaluator,
    "plan_quality": PlanQualityEvaluator,
    "f1_metric": F1MetricEvaluator,
    "self_attention": SelfAttentionEvaluator,
    "oscillation": OscillationEvaluator,
    "answer_sanitize": AnswerSanitizeEvaluator,
    "rate_limiting": RateLimitEvaluator,
    "tool_blocklist": BlocklistEvaluator,
    "param_validation": ParamValidationEvaluator,
}


# ─── Main Runner ────────────────────────────────────────────────────────────

class EvalRunner:
    """
    Main evaluation runner.

    Loads test cases, dispatches to evaluators, aggregates results.
    """

    def __init__(self, cases_path: Path | None = None):
        self._cases = load_test_cases(cases_path)

    @property
    def total_cases(self) -> int:
        return len(self._cases)

    def run_all(
        self,
        category: str | None = None,
        case_ids: list[str] | None = None,
    ) -> MetricsSummary:
        """Run all (or filtered) test cases and aggregate."""
        cases = filter_cases(self._cases, category, case_ids)
        results: list[EvalResult] = []

        for case in cases:
            cat = case.get("category", "unknown")
            evaluator_cls = _EVALUATORS.get(cat)
            if not evaluator_cls:
                # Skip unsupported categories (e.g., end_to_end needs live LLM)
                continue

            evaluator = evaluator_cls()
            try:
                result = evaluator.evaluate(case)
                results.append(result)
            except Exception as e:
                results.append(EvalResult(
                    case_id=case.get("id", "unknown"),
                    category=cat,
                    passed=False,
                    score=0.0,
                    details=f"Evaluator error: {e}",
                ))

        return MetricsAggregator.aggregate(results)

    def run_single(self, case_id: str) -> EvalResult | None:
        """Run a single test case by ID."""
        for case in self._cases:
            if case.get("id") == case_id:
                cat = case.get("category", "unknown")
                evaluator_cls = _EVALUATORS.get(cat)
                if not evaluator_cls:
                    return None
                return evaluator_cls().evaluate(case)
        return None

    def get_categories(self) -> list[str]:
        """Get all available categories."""
        return sorted({c.get("category", "unknown") for c in self._cases})

    @staticmethod
    def format_report(summary: MetricsSummary) -> str:
        """Format a human-readable report."""
        return MetricsAggregator.format_report(summary)
