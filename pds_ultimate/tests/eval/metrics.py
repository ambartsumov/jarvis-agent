"""
PDS-Ultimate Evaluation Metrics
================================
Precision-oriented metrics for measuring agent quality.

Metrics:
- ModeAccuracy: correct execution mode selection
- ToolSelectionF1: precision/recall of tool selection
- ResponseQuality: heuristic answer quality scoring
- LatencyProfile: timing distribution analysis
- SubAgentClassificationAccuracy: sub-agent type accuracy
- PlanQuality: DAG plan structure scoring
- OverallScore: weighted aggregate of all metrics
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

# ─── Single Evaluation Result ───────────────────────────────────────────────


@dataclass
class EvalResult:
    """Result of evaluating a single test case."""
    case_id: str
    category: str
    passed: bool
    score: float  # 0.0 - 1.0
    expected: Any = None
    actual: Any = None
    details: str = ""
    latency_ms: float = 0.0


# ─── Aggregated Metrics ─────────────────────────────────────────────────────

@dataclass
class MetricsSummary:
    """Aggregated metrics across all evaluated cases."""
    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    overall_score: float = 0.0

    # Per-category scores
    category_scores: dict[str, float] = field(default_factory=dict)
    category_counts: dict[str, int] = field(default_factory=dict)

    # Specific metrics
    mode_accuracy: float = 0.0
    tool_selection_f1: float = 0.0
    response_quality: float = 0.0
    sub_agent_accuracy: float = 0.0
    plan_quality: float = 0.0

    # Latency
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    latency_mean_ms: float = 0.0

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total_cases if self.total_cases else 0.0


# ─── Metric Calculators ─────────────────────────────────────────────────────

class ModeAccuracyMetric:
    """
    Measures if the agent selects the correct execution mode.

    Modes: simple, tool_loop, planned
    """

    @staticmethod
    def evaluate(expected_mode: str, actual_mode: str) -> EvalResult:
        match = expected_mode == actual_mode
        return EvalResult(
            case_id="",
            category="mode_selection",
            passed=match,
            score=1.0 if match else 0.0,
            expected=expected_mode,
            actual=actual_mode,
            details=f"Expected mode '{expected_mode}', got '{actual_mode}'"
            if not match else "Mode matched",
        )


class ToolSelectionMetric:
    """
    Measures tool selection quality using F1 score.

    F1 = 2 * (precision * recall) / (precision + recall)
    """

    @staticmethod
    def precision(expected_tools: set[str], actual_tools: set[str]) -> float:
        """What fraction of selected tools were correct?"""
        if not actual_tools:
            return 1.0 if not expected_tools else 0.0
        return len(expected_tools & actual_tools) / len(actual_tools)

    @staticmethod
    def recall(expected_tools: set[str], actual_tools: set[str]) -> float:
        """What fraction of expected tools were selected?"""
        if not expected_tools:
            return 1.0 if not actual_tools else 0.0
        return len(expected_tools & actual_tools) / len(expected_tools)

    @classmethod
    def f1(cls, expected_tools: set[str], actual_tools: set[str]) -> float:
        """Harmonic mean of precision and recall."""
        p = cls.precision(expected_tools, actual_tools)
        r = cls.recall(expected_tools, actual_tools)
        if p + r == 0:
            return 0.0
        return 2 * p * r / (p + r)

    @classmethod
    def evaluate(
        cls,
        expected_tools: list[str],
        actual_tools: list[str],
    ) -> EvalResult:
        exp_set = set(expected_tools)
        act_set = set(actual_tools)
        score = cls.f1(exp_set, act_set)

        return EvalResult(
            case_id="",
            category="tool_selection",
            passed=score >= 0.5,
            score=score,
            expected=sorted(expected_tools),
            actual=sorted(actual_tools),
            details=f"F1={score:.2f}, P={cls.precision(exp_set, act_set):.2f}, "
                    f"R={cls.recall(exp_set, act_set):.2f}",
        )


class ResponseQualityMetric:
    """
    Heuristic response quality scoring.

    Criteria:
    - Non-empty answer (+0.2)
    - Reasonable length (+0.2)
    - No JSON leaks (+0.15)
    - No hallucination markers (+0.15)
    - No excessive repetition (+0.15)
    - Keyword coverage from query (+0.15)
    """

    _HALLUCINATION_MARKERS: frozenset[str] = frozenset({
        "к сожалению, я не могу",
        "как языковая модель",
        "as an ai",
        "i cannot",
        "i apologize",
    })

    @classmethod
    def evaluate(cls, query: str, answer: str) -> EvalResult:
        if not answer or not answer.strip():
            return EvalResult(
                case_id="", category="response_quality",
                passed=False, score=0.0,
                details="Empty answer",
            )

        score = 0.0
        issues: list[str] = []

        # 1. Non-empty (+0.2)
        if len(answer.strip()) >= 5:
            score += 0.2
        else:
            issues.append("too_short")

        # 2. Reasonable length (+0.2)
        q_len = len(query)
        a_len = len(answer)
        if q_len > 100 and a_len < 20:
            issues.append("too_brief_for_complex_query")
        elif a_len > 5000 and q_len < 50:
            issues.append("excessively_long")
        else:
            score += 0.2

        # 3. No JSON leaks (+0.15)
        stripped = answer.strip()
        if stripped.startswith("{") and '"action"' in stripped:
            issues.append("json_leak")
        else:
            score += 0.15

        # 4. No hallucination markers (+0.15)
        answer_lower = answer.lower()
        if any(m in answer_lower for m in cls._HALLUCINATION_MARKERS):
            issues.append("hallucination_marker")
        else:
            score += 0.15

        # 5. No excessive repetition (+0.15)
        sentences = [s.strip() for s in answer.split(".") if s.strip()]
        if len(sentences) > 3:
            unique = len({s.lower() for s in sentences})
            if unique < len(sentences) * 0.5:
                issues.append("excessive_repetition")
            else:
                score += 0.15
        else:
            score += 0.15

        # 6. Keyword coverage (+0.15)
        query_words = set(query.lower().split())
        answer_words = set(answer.lower().split())
        if query_words:
            coverage = len(query_words & answer_words) / len(query_words)
            score += 0.15 * min(coverage * 2, 1.0)  # scale up small overlap

        return EvalResult(
            case_id="", category="response_quality",
            passed=score >= 0.5,
            score=min(1.0, score),
            details=f"Issues: {issues}" if issues else "Good quality",
        )


class SubAgentClassificationMetric:
    """Measures sub-agent type classification accuracy."""

    @staticmethod
    def evaluate(expected_type: str, actual_type: str) -> EvalResult:
        match = expected_type == actual_type
        return EvalResult(
            case_id="", category="sub_agent_classification",
            passed=match,
            score=1.0 if match else 0.0,
            expected=expected_type,
            actual=actual_type,
            details=f"Expected '{expected_type}', got '{actual_type}'"
            if not match else "Type matched",
        )


class PlanQualityMetric:
    """
    Evaluates DAG plan structure quality.

    Criteria:
    - Has at least 2 nodes (+0.2)
    - No orphan nodes (all deps exist) (+0.2)
    - Has synthesize terminal node (+0.2)
    - Parallel opportunities utilized (+0.2)
    - Reasonable number of steps (2-8) (+0.2)
    """

    @staticmethod
    def evaluate(plan_dict: dict) -> EvalResult:
        nodes = plan_dict.get("nodes", {})
        if not nodes:
            return EvalResult(
                case_id="", category="plan_quality",
                passed=False, score=0.0,
                details="Empty plan",
            )

        score = 0.0
        issues: list[str] = []

        # 1. At least 2 nodes
        if len(nodes) >= 2:
            score += 0.2
        else:
            issues.append("too_few_nodes")

        # 2. No orphan deps
        node_ids = set(nodes.keys())
        has_orphans = False
        for node_data in nodes.values():
            deps = node_data.get("depends_on", [])
            for dep in deps:
                if dep not in node_ids:
                    has_orphans = True
                    break
        if not has_orphans:
            score += 0.2
        else:
            issues.append("orphan_dependencies")

        # 3. Has synthesize node
        has_synthesize = any(
            "synthesize" in nid or "synthesize" in n.get(
                "description", "").lower()
            for nid, n in nodes.items()
        )
        if has_synthesize:
            score += 0.2
        else:
            issues.append("missing_synthesize")

        # 4. Parallel opportunities (nodes with no deps or shared deps)
        root_nodes = sum(
            1 for n in nodes.values()
            if not n.get("depends_on")
        )
        if root_nodes >= 2:
            score += 0.2
        else:
            issues.append("no_parallel_opportunities")

        # 5. Reasonable count
        if 2 <= len(nodes) <= 8:
            score += 0.2
        else:
            issues.append(f"node_count={len(nodes)}_outside_2-8")

        return EvalResult(
            case_id="", category="plan_quality",
            passed=score >= 0.6,
            score=score,
            details=f"Issues: {issues}" if issues else "Good plan",
        )


# ─── Latency Analysis ───────────────────────────────────────────────────────

class LatencyAnalyzer:
    """Computes latency percentiles from eval results."""

    @staticmethod
    def analyze(results: list[EvalResult]) -> dict[str, float]:
        latencies = [r.latency_ms for r in results if r.latency_ms > 0]
        if not latencies:
            return {"p50": 0.0, "p95": 0.0, "mean": 0.0, "max": 0.0}

        sorted_lat = sorted(latencies)
        return {
            "p50": sorted_lat[len(sorted_lat) // 2],
            "p95": sorted_lat[int(len(sorted_lat) * 0.95)],
            "mean": statistics.mean(sorted_lat),
            "max": max(sorted_lat),
        }


# ─── Metrics Aggregator ─────────────────────────────────────────────────────

class MetricsAggregator:
    """
    Aggregates individual EvalResults into a MetricsSummary.

    Weights:
    - mode_accuracy: 15%
    - tool_selection_f1: 25%
    - response_quality: 25%
    - sub_agent_accuracy: 15%
    - plan_quality: 10%
    - latency_factor: 10%
    """

    WEIGHTS: dict[str, float] = {
        "mode_selection": 0.15,
        "tool_selection": 0.25,
        "response_quality": 0.25,
        "sub_agent_classification": 0.15,
        "plan_quality": 0.10,
    }

    @classmethod
    def aggregate(cls, results: list[EvalResult]) -> MetricsSummary:
        if not results:
            return MetricsSummary()

        summary = MetricsSummary(
            total_cases=len(results),
            passed=sum(1 for r in results if r.passed),
            failed=sum(1 for r in results if not r.passed),
        )

        # Per-category aggregation
        cat_scores: dict[str, list[float]] = {}
        cat_counts: dict[str, int] = {}
        for r in results:
            cat_scores.setdefault(r.category, []).append(r.score)
            cat_counts[r.category] = cat_counts.get(r.category, 0) + 1

        for cat, scores in cat_scores.items():
            summary.category_scores[cat] = statistics.mean(
                scores) if scores else 0.0
        summary.category_counts = cat_counts

        # Specific metric scores
        summary.mode_accuracy = summary.category_scores.get(
            "mode_selection", 0.0)
        summary.tool_selection_f1 = summary.category_scores.get(
            "tool_selection", 0.0)
        summary.response_quality = summary.category_scores.get(
            "response_quality", 0.0)
        summary.sub_agent_accuracy = summary.category_scores.get(
            "sub_agent_classification", 0.0,
        )
        summary.plan_quality = summary.category_scores.get("plan_quality", 0.0)

        # Latency
        latency = LatencyAnalyzer.analyze(results)
        summary.latency_p50_ms = latency["p50"]
        summary.latency_p95_ms = latency["p95"]
        summary.latency_mean_ms = latency["mean"]

        # Overall weighted score
        weighted = 0.0
        weight_sum = 0.0
        for cat, weight in cls.WEIGHTS.items():
            if cat in summary.category_scores:
                weighted += summary.category_scores[cat] * weight
                weight_sum += weight

        # Latency bonus (fast = +10%)
        if latency["p95"] > 0:
            latency_score = max(0.0, 1.0 - (latency["p95"] / 10000))
            weighted += latency_score * 0.10
            weight_sum += 0.10

        summary.overall_score = weighted / weight_sum if weight_sum else 0.0

        return summary

    @staticmethod
    def format_report(summary: MetricsSummary) -> str:
        """Format metrics as a human-readable report."""
        lines = [
            "═══ PDS-Ultimate Evaluation Report ═══",
            "",
            f"Total cases: {summary.total_cases}",
            f"Passed: {summary.passed} ({summary.pass_rate:.1%})",
            f"Failed: {summary.failed}",
            "",
            "─── Category Scores ───",
        ]

        for cat, score in sorted(summary.category_scores.items()):
            count = summary.category_counts.get(cat, 0)
            lines.append(f"  {cat:30s} {score:.2f}  ({count} cases)")

        lines.extend([
            "",
            "─── Key Metrics ───",
            f"  Mode Accuracy:          {summary.mode_accuracy:.2f}",
            f"  Tool Selection F1:      {summary.tool_selection_f1:.2f}",
            f"  Response Quality:       {summary.response_quality:.2f}",
            f"  Sub-Agent Accuracy:     {summary.sub_agent_accuracy:.2f}",
            f"  Plan Quality:           {summary.plan_quality:.2f}",
            "",
            "─── Latency ───",
            f"  P50:  {summary.latency_p50_ms:.0f} ms",
            f"  P95:  {summary.latency_p95_ms:.0f} ms",
            f"  Mean: {summary.latency_mean_ms:.0f} ms",
            "",
            f"═══ OVERALL SCORE: {summary.overall_score:.2f} ═══",
        ])

        return "\n".join(lines)
