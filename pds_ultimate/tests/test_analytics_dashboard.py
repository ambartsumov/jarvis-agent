"""
Тесты Analytics Dashboard (Part 9)
========================================
MetricPoint, MetricSeries, KPI, TrendResult, PeriodComparison,
MetricsCollector, KPITracker, TrendAnalyzer, ReportFormatter,
AnalyticsDashboard.
~65 тестов.
"""

from datetime import datetime

from pds_ultimate.core.analytics_dashboard import (
    KPI,
    AnalyticsDashboard,
    KPIStatus,
    KPITracker,
    MetricPoint,
    MetricsCollector,
    MetricSeries,
    MetricType,
    Period,
    PeriodComparison,
    ReportFormatter,
    TrendAnalyzer,
    TrendDirection,
    TrendResult,
    analytics_dashboard,
)

# ═══════════════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════════════


class TestEnums:
    """Enum smoke tests."""

    def test_metric_type(self):
        assert MetricType.REVENUE.value == "revenue"
        assert MetricType.EXPENSE.value == "expense"
        assert MetricType.PROFIT.value == "profit"
        assert MetricType.CUSTOM.value == "custom"

    def test_period(self):
        assert Period.DAY.value == "day"
        assert Period.WEEK.value == "week"
        assert Period.MONTH.value == "month"
        assert Period.QUARTER.value == "quarter"
        assert Period.YEAR.value == "year"

    def test_trend_direction(self):
        assert TrendDirection.UP.value == "up"
        assert TrendDirection.DOWN.value == "down"
        assert TrendDirection.STABLE.value == "stable"
        assert TrendDirection.VOLATILE.value == "volatile"

    def test_kpi_status(self):
        assert KPIStatus.EXCEEDED.value == "exceeded"
        assert KPIStatus.ACHIEVED.value == "achieved"
        assert KPIStatus.ON_TRACK.value == "on_track"
        assert KPIStatus.AT_RISK.value == "at_risk"
        assert KPIStatus.BEHIND.value == "behind"


# ═══════════════════════════════════════════════════════════════════════════════
# MetricPoint
# ═══════════════════════════════════════════════════════════════════════════════


class TestMetricPoint:
    """MetricPoint — одна точка метрики."""

    def test_create(self):
        p = MetricPoint(timestamp=datetime.utcnow(), value=42.0)
        assert p.value == 42.0
        assert p.timestamp is not None

    def test_create_with_label(self):
        p = MetricPoint(timestamp=datetime.utcnow(), value=10, label="prod")
        assert p.label == "prod"

    def test_to_dict(self):
        p = MetricPoint(timestamp=datetime.utcnow(), value=5.5)
        d = p.to_dict()
        assert d["value"] == 5.5
        assert "timestamp" in d


# ═══════════════════════════════════════════════════════════════════════════════
# MetricSeries
# ═══════════════════════════════════════════════════════════════════════════════


class TestMetricSeries:
    """MetricSeries — серия точек одной метрики."""

    def test_create(self):
        s = MetricSeries(
            name="revenue", metric_type=MetricType.REVENUE, unit="USD")
        assert s.name == "revenue"
        assert s.unit == "USD"
        assert len(s.points) == 0

    def test_add_point(self):
        s = MetricSeries(name="orders", metric_type=MetricType.CUSTOM)
        s.add_point(10)
        s.add_point(20)
        s.add_point(30)
        assert len(s.points) == 3

    def test_values(self):
        s = MetricSeries(name="x", metric_type=MetricType.CUSTOM)
        s.add_point(1)
        s.add_point(2)
        s.add_point(3)
        assert s.values == [1, 2, 3]

    def test_total(self):
        s = MetricSeries(name="x", metric_type=MetricType.CUSTOM)
        s.add_point(10)
        s.add_point(20)
        assert s.total == 30

    def test_average(self):
        s = MetricSeries(name="x", metric_type=MetricType.CUSTOM)
        s.add_point(10)
        s.add_point(20)
        s.add_point(30)
        assert s.average == 20.0

    def test_min_max(self):
        s = MetricSeries(name="x", metric_type=MetricType.CUSTOM)
        for v in [10, 20, 30, 40, 50]:
            s.add_point(v)
        assert s.min_value == 10
        assert s.max_value == 50

    def test_count(self):
        s = MetricSeries(name="x", metric_type=MetricType.CUSTOM)
        s.add_point(1)
        s.add_point(2)
        assert s.count == 2

    def test_empty_stats(self):
        s = MetricSeries(name="x", metric_type=MetricType.CUSTOM)
        assert s.count == 0
        assert s.average == 0.0

    def test_to_dict(self):
        s = MetricSeries(name="rev", metric_type=MetricType.CUSTOM, unit="$")
        s.add_point(100)
        d = s.to_dict()
        assert d["name"] == "rev"
        assert d["unit"] == "$"
        assert d["count"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# KPI
# ═══════════════════════════════════════════════════════════════════════════════


class TestKPI:
    """KPI — Key Performance Indicator."""

    def test_create(self):
        k = KPI(name="Revenue", target_value=1000, unit="USD")
        assert k.name == "Revenue"
        assert k.current_value == 0
        assert k.target_value == 1000

    def test_progress(self):
        k = KPI(name="R", target_value=100, current_value=50)
        assert k.progress == 0.5

    def test_progress_zero_target(self):
        k = KPI(name="R", target_value=0)
        assert k.progress == 0.0

    def test_progress_percent(self):
        k = KPI(name="R", target_value=200, current_value=100)
        assert k.progress_percent == 50.0

    def test_status_exceeded(self):
        k = KPI(name="R", target_value=100, current_value=120)
        assert k.status == KPIStatus.EXCEEDED

    def test_status_achieved(self):
        k = KPI(name="R", target_value=100, current_value=100)
        assert k.status == KPIStatus.ACHIEVED

    def test_status_on_track(self):
        k = KPI(name="R", target_value=100, current_value=75)
        assert k.status == KPIStatus.ON_TRACK

    def test_status_at_risk(self):
        k = KPI(name="R", target_value=100, current_value=50)
        assert k.status == KPIStatus.AT_RISK

    def test_status_behind(self):
        k = KPI(name="R", target_value=100, current_value=10)
        assert k.status == KPIStatus.BEHIND

    def test_update_cumulative(self):
        k = KPI(name="R", target_value=100)
        k.update(30)
        assert k.current_value == 30
        k.update(70)
        assert k.current_value == 100

    def test_update_non_cumulative(self):
        k = KPI(name="R", target_value=100)
        k.update(30, cumulative=False)
        assert k.current_value == 30
        k.update(70, cumulative=False)
        assert k.current_value == 70

    def test_to_dict(self):
        k = KPI(name="Sales", target_value=500, current_value=250, unit="$")
        d = k.to_dict()
        assert d["name"] == "Sales"
        assert d["target"] == 500
        assert d["current"] == 250
        assert d["progress"] == 50.0


# ═══════════════════════════════════════════════════════════════════════════════
# TrendResult
# ═══════════════════════════════════════════════════════════════════════════════


class TestTrendResult:
    """TrendResult — результат анализа тренда."""

    def test_create(self):
        t = TrendResult(
            direction=TrendDirection.UP,
            change_percent=10.0,
            average=50.0,
            slope=2.5,
            confidence=0.9,
        )
        assert t.direction == TrendDirection.UP
        assert t.slope == 2.5

    def test_to_dict(self):
        t = TrendResult(
            direction=TrendDirection.DOWN,
            change_percent=-5.0,
            average=30.0,
            slope=-1.0,
            confidence=0.8,
        )
        d = t.to_dict()
        assert d["direction"] == "down"
        assert d["slope"] == -1.0


# ═══════════════════════════════════════════════════════════════════════════════
# PeriodComparison
# ═══════════════════════════════════════════════════════════════════════════════


class TestPeriodComparison:
    """PeriodComparison — сравнение периодов."""

    def test_create(self):
        pc = PeriodComparison(
            period_1_label="Week 1",
            period_2_label="Week 2",
            metric_name="revenue",
            value_1=1000,
            value_2=1200,
            change=200,
            change_percent=20.0,
            improved=True,
        )
        assert pc.metric_name == "revenue"
        assert pc.change_percent == 20.0

    def test_to_dict(self):
        pc = PeriodComparison(
            period_1_label="P1",
            period_2_label="P2",
            metric_name="orders",
            value_1=40,
            value_2=50,
            change=10,
            change_percent=25.0,
            improved=True,
        )
        d = pc.to_dict()
        assert "change_percent" in d
        assert d["improved"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# MetricsCollector
# ═══════════════════════════════════════════════════════════════════════════════


class TestMetricsCollector:
    """MetricsCollector — сбор метрик."""

    def test_record_and_get(self):
        mc = MetricsCollector()
        mc.record("cpu", 80.5, unit="%")
        mc.record("cpu", 75.0)
        series = mc.get_series("cpu")
        assert series is not None
        assert len(series.points) == 2

    def test_get_nonexistent(self):
        mc = MetricsCollector()
        assert mc.get_series("nope") is None

    def test_list_series(self):
        mc = MetricsCollector()
        mc.record("a", 1)
        mc.record("b", 2)
        names = mc.list_series()
        assert "a" in names
        assert "b" in names

    def test_get_summary(self):
        mc = MetricsCollector()
        mc.record("x", 10)
        mc.record("x", 20)
        summary = mc.get_summary()
        assert "x" in summary


# ═══════════════════════════════════════════════════════════════════════════════
# KPITracker
# ═══════════════════════════════════════════════════════════════════════════════


class TestKPITracker:
    """KPITracker — отслеживание KPI."""

    def test_create_kpi(self):
        kt = KPITracker()
        kpi = kt.create_kpi(name="Revenue", target_value=1000, unit="$")
        assert kpi.name == "Revenue"

    def test_find_kpi(self):
        kt = KPITracker()
        kt.create_kpi(name="Sales", target_value=100)
        kpi = kt.find_kpi("Sales")
        assert kpi is not None
        assert kpi.name == "Sales"

    def test_find_nonexistent(self):
        kt = KPITracker()
        assert kt.find_kpi("Nope") is None

    def test_update_kpi(self):
        kt = KPITracker()
        kpi = kt.create_kpi(name="Orders", target_value=50)
        updated = kt.update_kpi(kpi.id, 30)
        assert updated is not None
        assert updated.current_value == 30

    def test_update_nonexistent(self):
        kt = KPITracker()
        assert kt.update_kpi("fake-id", 10) is None

    def test_get_at_risk(self):
        kt = KPITracker()
        kpi = kt.create_kpi(name="Low", target_value=100)
        kt.update_kpi(kpi.id, 45, cumulative=False)
        at_risk = kt.get_at_risk()
        assert len(at_risk) >= 1

    def test_get_achieved(self):
        kt = KPITracker()
        kpi = kt.create_kpi(name="Done", target_value=100)
        kt.update_kpi(kpi.id, 100, cumulative=False)
        achieved = kt.get_achieved()
        assert len(achieved) == 1

    def test_format_kpi_board(self):
        kt = KPITracker()
        kpi = kt.create_kpi(name="Rev", target_value=1000)
        kt.update_kpi(kpi.id, 750)
        text = kt.format_kpi_board()
        assert "Rev" in text

    def test_format_kpi_board_empty(self):
        kt = KPITracker()
        text = kt.format_kpi_board()
        assert isinstance(text, str)

    def test_get_stats(self):
        kt = KPITracker()
        kt.create_kpi(name="A", target_value=100)
        kt.create_kpi(name="B", target_value=200)
        stats = kt.get_stats()
        assert stats["total"] == 2


# ═══════════════════════════════════════════════════════════════════════════════
# TrendAnalyzer
# ═══════════════════════════════════════════════════════════════════════════════


class TestTrendAnalyzer:
    """TrendAnalyzer — анализ трендов."""

    def _make_series(self, values):
        s = MetricSeries(name="test", metric_type=MetricType.CUSTOM)
        for v in values:
            s.add_point(v)
        return s

    def test_analyze_uptrend(self):
        ta = TrendAnalyzer()
        s = self._make_series([100, 110, 120, 130, 140])
        result = ta.analyze(s)
        assert result.direction == TrendDirection.UP
        assert result.slope > 0

    def test_analyze_downtrend(self):
        ta = TrendAnalyzer()
        s = self._make_series([140, 130, 120, 110, 100])
        result = ta.analyze(s)
        assert result.direction == TrendDirection.DOWN
        assert result.slope < 0

    def test_analyze_stable(self):
        ta = TrendAnalyzer()
        s = self._make_series([10, 10, 10, 10, 10])
        result = ta.analyze(s)
        assert result.direction == TrendDirection.STABLE

    def test_analyze_single_point(self):
        ta = TrendAnalyzer()
        s = self._make_series([42])
        result = ta.analyze(s)
        assert result.direction == TrendDirection.STABLE
        assert result.confidence == 0.0

    def test_forecast_simple(self):
        ta = TrendAnalyzer()
        s = self._make_series([100, 110, 120, 130, 140])
        forecast = ta.forecast_simple(s, periods_ahead=3)
        assert len(forecast) == 3
        assert forecast[0] > 140

    def test_forecast_single_point(self):
        ta = TrendAnalyzer()
        s = self._make_series([42])
        forecast = ta.forecast_simple(s, periods_ahead=3)
        assert len(forecast) == 3


# ═══════════════════════════════════════════════════════════════════════════════
# ReportFormatter
# ═══════════════════════════════════════════════════════════════════════════════


class TestReportFormatter:
    """ReportFormatter — форматирование отчётов."""

    def test_format_dashboard(self):
        rf = ReportFormatter()
        s = MetricSeries(name="rev", metric_type=MetricType.REVENUE, unit="$")
        for v in [100, 200, 300]:
            s.add_point(v)
        text = rf.format_dashboard({"rev": s}, [], None)
        assert "rev" in text

    def test_format_trend_report(self):
        rf = ReportFormatter()
        tr = TrendResult(
            direction=TrendDirection.UP, slope=5.0, confidence=0.95,
            change_percent=10.0, average=50.0,
        )
        text = rf.format_trend_report({"Revenue": tr})
        assert "Revenue" in text


# ═══════════════════════════════════════════════════════════════════════════════
# AnalyticsDashboard (facade)
# ═══════════════════════════════════════════════════════════════════════════════


class TestAnalyticsDashboard:
    """AnalyticsDashboard — главный фасад."""

    def test_record_metric(self):
        ad = AnalyticsDashboard()
        ad.record_metric("visits", 100, unit="count")
        series = ad.collector.get_series("visits")
        assert series is not None

    def test_create_kpi(self):
        ad = AnalyticsDashboard()
        kpi = ad.create_kpi("Revenue", target=5000, unit="$")
        assert kpi.name == "Revenue"
        assert kpi.target_value == 5000

    def test_update_kpi(self):
        ad = AnalyticsDashboard()
        ad.create_kpi("Sales", target=100)
        kpi = ad.update_kpi("Sales", 75)
        assert kpi is not None
        assert kpi.current_value == 75

    def test_update_kpi_nonexistent(self):
        ad = AnalyticsDashboard()
        assert ad.update_kpi("Nope", 10) is None

    def test_generate_dashboard(self):
        ad = AnalyticsDashboard()
        ad.record_metric("rev", 1000)
        ad.create_kpi("Goal", target=2000)
        text = ad.generate_dashboard()
        assert isinstance(text, str)
        assert len(text) > 0

    def test_generate_trend_report(self):
        ad = AnalyticsDashboard()
        for v in [10, 20, 30, 40]:
            ad.record_metric("growth", v)
        report = ad.generate_trend_report()
        assert isinstance(report, str)

    def test_forecast(self):
        ad = AnalyticsDashboard()
        for v in [10, 20, 30, 40, 50]:
            ad.record_metric("sales", v)
        forecast = ad.forecast("sales")
        assert isinstance(forecast, list)
        assert len(forecast) > 0

    def test_forecast_nonexistent(self):
        ad = AnalyticsDashboard()
        result = ad.forecast("nonexistent")
        assert result == []

    def test_get_stats(self):
        ad = AnalyticsDashboard()
        stats = ad.get_stats()
        assert "metrics" in stats
        assert "kpi" in stats

    def test_global_instance(self):
        assert analytics_dashboard is not None
        assert isinstance(analytics_dashboard, AnalyticsDashboard)
