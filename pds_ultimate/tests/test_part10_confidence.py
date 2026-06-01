"""
Tests for Part 10 — Confidence Tracker
"""

import pytest

from pds_ultimate.core.confidence_tracker import (
    AutoSearchTrigger,
    ConfidenceCalibrator,
    ConfidenceEstimator,
    ConfidenceLevel,
    ConfidenceScore,
    ConfidenceTracker,
    SearchAction,
    TrackedOutput,
    UncertaintyTracker,
    confidence_tracker,
)


class TestConfidenceLevel:
    """Тесты ConfidenceLevel."""

    def test_levels(self):
        assert ConfidenceLevel.VERY_HIGH == "very_high"
        assert ConfidenceLevel.LOW == "low"


class TestConfidenceScore:
    """Тесты ConfidenceScore."""

    def test_create(self):
        score = ConfidenceScore(
            value=0.85,
            level=ConfidenceLevel.HIGH,
        )
        assert score.value == 0.85
        assert not score.needs_additional_search

    def test_needs_search_low(self):
        score = ConfidenceScore(
            value=0.3,
            level=ConfidenceLevel.LOW,
        )
        assert score.needs_additional_search is True

    def test_emoji(self):
        very_high = ConfidenceScore(
            value=0.96, level=ConfidenceLevel.VERY_HIGH)
        high = ConfidenceScore(value=0.85, level=ConfidenceLevel.HIGH)
        low = ConfidenceScore(value=0.35, level=ConfidenceLevel.LOW)
        very_low = ConfidenceScore(value=0.15, level=ConfidenceLevel.VERY_LOW)
        assert "🟢" in very_high.emoji
        assert "🟡" in high.emoji
        assert "🔴" in low.emoji
        assert "⚫" in very_low.emoji

    def test_to_dict(self):
        score = ConfidenceScore(
            value=0.7,
            level=ConfidenceLevel.MEDIUM,
            factors={"src": 0.8},
        )
        d = score.to_dict()
        assert "value" in d
        assert "level" in d
        assert "factors" in d


class TestTrackedOutput:
    """Тесты TrackedOutput."""

    def test_create(self):
        score = ConfidenceScore(value=0.8, level=ConfidenceLevel.HIGH)
        output = TrackedOutput(
            content="Ответ",
            confidence=score,
            query="вопрос",
        )
        assert output.content == "Ответ"

    def test_format_with_confidence(self):
        score = ConfidenceScore(value=0.75, level=ConfidenceLevel.HIGH)
        output = TrackedOutput(content="Ответ", confidence=score)
        formatted = output.format_with_confidence()
        assert "Ответ" in formatted
        assert "75%" in formatted

    def test_to_dict(self):
        score = ConfidenceScore(value=0.6, level=ConfidenceLevel.MEDIUM)
        output = TrackedOutput(content="X", confidence=score)
        d = output.to_dict()
        assert "content" in d
        assert "confidence" in d


class TestConfidenceEstimator:
    """Тесты ConfidenceEstimator."""

    def test_estimate_basic(self):
        est = ConfidenceEstimator()
        score = est.estimate("Тестовый текст для оценки")
        assert isinstance(score, ConfidenceScore)
        assert 0.0 <= score.value <= 1.0

    def test_high_confidence(self):
        est = ConfidenceEstimator()
        score = est.estimate(
            "Точный ответ с данными",
            source_count=5,
            source_agreement=0.95,
            data_freshness=0.9,
            evidence_strength=0.9,
        )
        assert score.value > 0.5

    def test_low_confidence_hedging(self):
        est = ConfidenceEstimator()
        score = est.estimate(
            "Возможно, может быть, вероятно это так, но не факт",
            source_count=0,
            source_agreement=0.1,
        )
        assert score.value < 0.7

    def test_uncertainties_detected(self):
        est = ConfidenceEstimator()
        score = est.estimate(
            "Текст",
            source_count=0,
            data_freshness=0.1,
        )
        assert len(score.uncertainties) > 0

    def test_suggested_action(self):
        est = ConfidenceEstimator()
        score = est.estimate("X", source_count=0)
        assert score.suggested_action is not None


class TestUncertaintyTracker:
    """Тесты UncertaintyTracker."""

    def test_track(self):
        tracker = UncertaintyTracker()
        score = ConfidenceScore(value=0.5, level=ConfidenceLevel.MEDIUM)
        tracker.track(score)
        assert tracker.average_confidence == pytest.approx(0.5, abs=0.01)

    def test_multiple_tracks(self):
        tracker = UncertaintyTracker()
        for v in [0.3, 0.5, 0.7]:
            score = ConfidenceScore(
                value=v,
                level=ConfidenceLevel.MEDIUM,
            )
            tracker.track(score)
        assert tracker.average_confidence == pytest.approx(0.5, abs=0.01)

    def test_low_confidence_rate(self):
        tracker = UncertaintyTracker()
        for v in [0.3, 0.4, 0.8, 0.9]:
            score = ConfidenceScore(
                value=v,
                level=ConfidenceLevel.MEDIUM
                if v >= 0.5 else ConfidenceLevel.LOW,
            )
            tracker.track(score)
        rate = tracker.low_confidence_rate
        assert 0.0 <= rate <= 1.0

    def test_record_outcome(self):
        tracker = UncertaintyTracker()
        tracker.record_outcome(
            SearchAction.EXPAND_QUERY, True, 0.4, 0.8,
        )
        eff = tracker.get_action_effectiveness()
        assert isinstance(eff, dict)

    def test_get_stats(self):
        tracker = UncertaintyTracker()
        stats = tracker.get_stats()
        assert "total_tracked" in stats


class TestAutoSearchTrigger:
    """Тесты AutoSearchTrigger."""

    def test_should_search_low_confidence(self):
        trigger = AutoSearchTrigger(threshold=0.7)
        score = ConfidenceScore(value=0.3, level=ConfidenceLevel.LOW)
        assert trigger.should_search(score) is True

    def test_should_not_search_high_confidence(self):
        trigger = AutoSearchTrigger(threshold=0.7)
        score = ConfidenceScore(value=0.9, level=ConfidenceLevel.VERY_HIGH)
        assert trigger.should_search(score) is False

    def test_get_search_plan(self):
        trigger = AutoSearchTrigger()
        score = ConfidenceScore(
            value=0.3, level=ConfidenceLevel.LOW,
            suggested_action=SearchAction.FULL_RESEARCH,
        )
        plan = trigger.get_search_plan(score, iteration=0)
        assert plan is not None
        assert "action" in plan

    def test_threshold_property(self):
        trigger = AutoSearchTrigger(threshold=0.6)
        assert trigger.threshold == 0.6
        trigger.threshold = 0.8
        assert trigger.threshold == 0.8

    def test_get_stats(self):
        trigger = AutoSearchTrigger()
        score = ConfidenceScore(value=0.3, level=ConfidenceLevel.LOW)
        trigger.should_search(score)
        stats = trigger.get_stats()
        assert "threshold" in stats
        assert "triggers_fired" in stats


class TestConfidenceCalibrator:
    """Тесты ConfidenceCalibrator."""

    def test_record_and_calibrate(self):
        cal = ConfidenceCalibrator()
        cal.record(0.8, True)
        cal.record(0.8, True)
        cal.record(0.8, False)
        result = cal.calibrate(0.8)
        assert 0.0 <= result <= 1.0

    def test_no_data(self):
        cal = ConfidenceCalibrator()
        result = cal.calibrate(0.5)
        assert result == 0.5  # no adjustment

    def test_overconfident_detection(self):
        cal = ConfidenceCalibrator()
        for _ in range(20):
            cal.record(0.9, False)  # Always wrong at 0.9
        assert cal.is_overconfident is True

    def test_get_stats(self):
        cal = ConfidenceCalibrator()
        stats = cal.get_stats()
        assert "total_predictions" in stats


class TestConfidenceTrackerFacade:
    """Тесты фасада ConfidenceTracker."""

    def test_estimate(self):
        tracker = ConfidenceTracker()
        score = tracker.estimate("Тестовый текст")
        assert isinstance(score, ConfidenceScore)

    def test_needs_search(self):
        tracker = ConfidenceTracker()
        score = ConfidenceScore(value=0.3, level=ConfidenceLevel.LOW)
        assert tracker.needs_search(score) is True

    def test_get_search_plan(self):
        tracker = ConfidenceTracker()
        score = ConfidenceScore(
            value=0.3, level=ConfidenceLevel.LOW,
            suggested_action=SearchAction.EXPAND_QUERY,
        )
        plan = tracker.get_search_plan(score)
        assert plan is not None

    def test_wrap_output(self):
        tracker = ConfidenceTracker()
        score = ConfidenceScore(value=0.8, level=ConfidenceLevel.HIGH)
        output = tracker.wrap_output("Ответ", score, "вопрос")
        assert isinstance(output, TrackedOutput)
        assert output.content == "Ответ"

    def test_record_feedback(self):
        tracker = ConfidenceTracker()
        tracker.record_feedback(0.8, True)
        stats = tracker.get_stats()
        assert isinstance(stats, dict)

    def test_get_stats(self):
        tracker = ConfidenceTracker()
        stats = tracker.get_stats()
        assert "estimator" in stats or "uncertainty" in stats


class TestGlobalInstance:
    """Тест глобального экземпляра."""

    def test_global_exists(self):
        assert confidence_tracker is not None
        assert isinstance(confidence_tracker, ConfidenceTracker)
