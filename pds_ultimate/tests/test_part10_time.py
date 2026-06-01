"""
Tests for Part 10 — Time & Relevance Engine
"""

import time
from datetime import datetime

import pytest

from pds_ultimate.core.time_relevance import (
    FreshnessGrade,
    FreshnessReport,
    FreshnessScorer,
    RelevanceEntry,
    RelevanceTracker,
    TemporalExtractor,
    TemporalMarker,
    TemporalScope,
    TimeDecayCalculator,
    TimeRelevanceEngine,
    time_relevance,
)


class TestFreshnessGrade:
    """Тесты FreshnessGrade."""

    def test_values(self):
        assert FreshnessGrade.FRESH == "fresh"
        assert FreshnessGrade.OUTDATED == "outdated"

    def test_emoji(self):
        assert FreshnessGrade.FRESH.emoji == "🟢"
        assert FreshnessGrade.STALE.emoji == "🔴"
        assert FreshnessGrade.OUTDATED.emoji == "⚫"


class TestTemporalMarker:
    """Тесты TemporalMarker."""

    def test_create(self):
        marker = TemporalMarker(
            text="2024",
            date=datetime(2024, 1, 1),
        )
        assert marker.text == "2024"
        assert marker.age_days > 0

    def test_no_date(self):
        marker = TemporalMarker(text="unknown", date=None)
        assert marker.age_days == float('inf')

    def test_to_dict(self):
        marker = TemporalMarker(
            text="2024-01-15",
            date=datetime(2024, 1, 15),
            scope=TemporalScope.DAILY,
        )
        d = marker.to_dict()
        assert "text" in d
        assert "date" in d
        assert "scope" in d


class TestFreshnessReport:
    """Тесты FreshnessReport."""

    def test_create(self):
        report = FreshnessReport(
            grade=FreshnessGrade.FRESH,
            score=0.95,
            data_age_days=0.5,
        )
        assert report.needs_update is False

    def test_to_dict(self):
        report = FreshnessReport(
            grade=FreshnessGrade.STALE,
            score=0.3,
            data_age_days=200,
            needs_update=True,
        )
        d = report.to_dict()
        assert d["needs_update"] is True
        assert "grade" in d


class TestTemporalExtractor:
    """Тесты TemporalExtractor."""

    def test_extract_year(self):
        ext = TemporalExtractor()
        markers = ext.extract("Данные за 2024 год")
        assert len(markers) >= 1
        years = [m for m in markers if m.date and m.date.year == 2024]
        assert len(years) >= 1

    def test_extract_iso_date(self):
        ext = TemporalExtractor()
        markers = ext.extract("Обновлено 2024-06-15")
        assert len(markers) >= 1
        assert any(
            m.date and m.date.day == 15 and m.date.month == 6
            for m in markers
        )

    def test_extract_dot_date(self):
        ext = TemporalExtractor()
        markers = ext.extract("Дата: 15.06.2024")
        assert len(markers) >= 1

    def test_extract_quarter(self):
        ext = TemporalExtractor()
        markers = ext.extract("Результаты Q3 2024")
        assert len(markers) >= 1
        q_markers = [m for m in markers if m.scope == TemporalScope.QUARTERLY]
        assert len(q_markers) >= 1

    def test_extract_month_name(self):
        ext = TemporalExtractor()
        markers = ext.extract("В январе 2024 произошло...")
        assert len(markers) >= 1

    def test_extract_relative_today(self):
        ext = TemporalExtractor()
        markers = ext.extract("Сегодня обновили данные")
        assert len(markers) >= 1
        today_markers = [m for m in markers if m.text == "сегодня"]
        assert len(today_markers) >= 1

    def test_extract_relative_yesterday(self):
        ext = TemporalExtractor()
        markers = ext.extract("Вчера был отчёт")
        assert len(markers) >= 1

    def test_extract_relative_period(self):
        ext = TemporalExtractor()
        markers = ext.extract("На прошлой неделе были изменения")
        assert len(markers) >= 1

    def test_no_dates(self):
        ext = TemporalExtractor()
        markers = ext.extract("Просто текст без дат")
        assert len(markers) == 0

    def test_get_oldest_date(self):
        ext = TemporalExtractor()
        markers = ext.extract("Данные с 2020 по 2024 год")
        oldest = ext.get_oldest_date(markers)
        if oldest:
            assert oldest.year <= 2024

    def test_get_newest_date(self):
        ext = TemporalExtractor()
        markers = ext.extract("Данные с 2020 по 2024 год")
        newest = ext.get_newest_date(markers)
        if newest:
            assert newest.year >= 2020

    def test_multiple_dates(self):
        ext = TemporalExtractor()
        markers = ext.extract(
            "В 2022 было одно, в Q1 2023 другое, а 15.06.2024 третье"
        )
        assert len(markers) >= 3


class TestFreshnessScorer:
    """Тесты FreshnessScorer."""

    def test_score_fresh_text(self):
        scorer = FreshnessScorer()
        report = scorer.score_text("Обновлено сегодня, все данные актуальны")
        assert report.grade in (FreshnessGrade.FRESH, FreshnessGrade.RECENT)

    def test_score_old_text(self):
        scorer = FreshnessScorer()
        report = scorer.score_text("По данным за 2020 год")
        assert report.grade in (
            FreshnessGrade.STALE, FreshnessGrade.OUTDATED,
            FreshnessGrade.AGING,
        )

    def test_score_no_dates(self):
        scorer = FreshnessScorer()
        report = scorer.score_text("Просто текст")
        assert report.grade == FreshnessGrade.CURRENT  # Default

    def test_score_age(self):
        scorer = FreshnessScorer()
        report = scorer.score_age(0.5)
        assert report.grade == FreshnessGrade.FRESH
        report2 = scorer.score_age(500)
        assert report2.grade == FreshnessGrade.OUTDATED

    def test_needs_update(self):
        scorer = FreshnessScorer()
        report = scorer.score_age(400)
        assert report.needs_update is True

    def test_recommendation(self):
        scorer = FreshnessScorer()
        report = scorer.score_age(200)
        assert len(report.recommendation) > 0


class TestTimeDecayCalculator:
    """Тесты TimeDecayCalculator."""

    def test_exponential_fresh(self):
        calc = TimeDecayCalculator()
        score = calc.exponential(0)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_exponential_half_life(self):
        calc = TimeDecayCalculator()
        score = calc.exponential(90, half_life_days=90)
        assert score == pytest.approx(0.5, abs=0.01)

    def test_exponential_old(self):
        calc = TimeDecayCalculator()
        score = calc.exponential(365)
        assert score < 0.5

    def test_linear_fresh(self):
        calc = TimeDecayCalculator()
        score = calc.linear(0)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_linear_max_age(self):
        calc = TimeDecayCalculator()
        score = calc.linear(365, max_age_days=365)
        assert score == pytest.approx(0.0, abs=0.01)

    def test_linear_beyond_max(self):
        calc = TimeDecayCalculator()
        score = calc.linear(500, max_age_days=365)
        assert score == 0.0

    def test_hyperbolic(self):
        calc = TimeDecayCalculator()
        score = calc.hyperbolic(0)
        assert score == pytest.approx(1.0, abs=0.01)
        score2 = calc.hyperbolic(100, alpha=0.01)
        assert score2 == pytest.approx(0.5, abs=0.01)

    def test_weighted_score(self):
        calc = TimeDecayCalculator()
        result = calc.weighted_score(0.8, 90, "exponential")
        assert 0.0 <= result <= 0.8

    def test_weighted_score_linear(self):
        calc = TimeDecayCalculator()
        result = calc.weighted_score(1.0, 180, "linear", max_age_days=365)
        assert 0.0 <= result <= 1.0

    def test_weighted_score_hyperbolic(self):
        calc = TimeDecayCalculator()
        result = calc.weighted_score(1.0, 50, "hyperbolic")
        assert 0.0 <= result <= 1.0


class TestRelevanceTracker:
    """Тесты RelevanceTracker."""

    def test_track(self):
        rt = RelevanceTracker()
        entry = rt.track("s1", "Source 1", relevance=0.8)
        assert entry.source_id == "s1"
        assert entry.relevance_score == 0.8

    def test_track_existing(self):
        rt = RelevanceTracker()
        rt.track("s2", "Source 2", relevance=0.5)
        entry = rt.track("s2", "Source 2", relevance=0.9)
        assert entry.access_count == 2
        assert entry.relevance_score == 0.9

    def test_get(self):
        rt = RelevanceTracker()
        rt.track("s3", "Source 3")
        assert rt.get("s3") is not None
        assert rt.get("unknown") is None

    def test_update_freshness(self):
        rt = RelevanceTracker()
        entry = RelevanceEntry(
            source_id="old",
            source_name="Old Source",
            first_seen=time.time() - 86400 * 200,
        )
        rt._entries["old"] = entry
        updated = rt.update_freshness()
        assert updated >= 0

    def test_get_stale(self):
        rt = RelevanceTracker()
        entry = RelevanceEntry(
            source_id="stale",
            source_name="Stale",
            first_seen=time.time() - 86400 * 500,
            freshness_score=0.1,
        )
        rt._entries["stale"] = entry
        stale = rt.get_stale(threshold=0.3)
        assert len(stale) >= 1

    def test_get_top(self):
        rt = RelevanceTracker()
        rt.track("a", "A", relevance=0.9)
        rt.track("b", "B", relevance=0.3)
        rt.track("c", "C", relevance=0.7)
        top = rt.get_top(2)
        assert len(top) == 2
        assert top[0].relevance_score >= top[1].relevance_score

    def test_remove(self):
        rt = RelevanceTracker()
        rt.track("rm1", "Remove me")
        assert rt.remove("rm1") is True
        assert rt.get("rm1") is None

    def test_enforce_limit(self):
        rt = RelevanceTracker(max_entries=3)
        for i in range(5):
            rt.track(f"lim{i}", f"Source {i}", relevance=i * 0.2)
        assert rt.count <= 3

    def test_get_stats(self):
        rt = RelevanceTracker()
        stats = rt.get_stats()
        assert "count" in stats

    def test_relevance_entry_touch(self):
        entry = RelevanceEntry(source_id="t1", source_name="Touch")
        old_count = entry.access_count
        entry.touch()
        assert entry.access_count == old_count + 1

    def test_combined_score(self):
        entry = RelevanceEntry(
            source_id="cs1", source_name="Combined",
            freshness_score=0.8, relevance_score=0.5,
        )
        assert entry.combined_score == pytest.approx(0.4, abs=0.01)


class TestTimeRelevanceEngineFacade:
    """Тесты фасада TimeRelevanceEngine."""

    def test_check_freshness(self):
        engine = TimeRelevanceEngine()
        report = engine.check_freshness("Данные за 2024 год")
        assert isinstance(report, FreshnessReport)

    def test_extract_dates(self):
        engine = TimeRelevanceEngine()
        markers = engine.extract_dates("В 2023 году произошло...")
        assert isinstance(markers, list)
        assert len(markers) >= 1

    def test_get_freshness_label(self):
        engine = TimeRelevanceEngine()
        label = engine.get_freshness_label("Обновлено сегодня")
        assert isinstance(label, str)
        assert len(label) > 0

    def test_apply_time_decay(self):
        engine = TimeRelevanceEngine()
        result = engine.apply_time_decay(0.8, age_days=90)
        assert 0.0 <= result <= 0.8

    def test_track_source(self):
        engine = TimeRelevanceEngine()
        entry = engine.track_source("src1", "Test Source", 0.7)
        assert entry.source_id == "src1"

    def test_get_stale_sources(self):
        engine = TimeRelevanceEngine()
        stale = engine.get_stale_sources()
        assert isinstance(stale, list)

    def test_get_stats(self):
        engine = TimeRelevanceEngine()
        stats = engine.get_stats()
        assert "sources" in stats


class TestGlobalInstance:
    """Тест глобального экземпляра."""

    def test_global_exists(self):
        assert time_relevance is not None
        assert isinstance(time_relevance, TimeRelevanceEngine)
