"""
Tests for Step 10: Observability (Metrics & Tracing)
======================================================
Tests for core/metrics.py and core/tracer.py.

Total: ~90 tests covering:
- Counter, Gauge, Histogram, Timer metric types
- MetricsRegistry
- Span, Trace data models
- TraceContext
- RequestTracer
- SpanContextManager
- Health check
- Thread safety basics
"""

import threading
import time

import pytest

from pds_ultimate.core.metrics import (
    Counter,
    Gauge,
    Histogram,
    MetricsRegistry,
    MetricType,
    MetricValue,
    Timer,
    metrics_registry,
)
from pds_ultimate.core.tracer import (
    RequestTracer,
    Span,
    SpanStatus,
    Trace,
    TraceContext,
    request_tracer,
)

# ═══════════════════════════════════════════════════════════════════════════════
# COUNTER
# ═══════════════════════════════════════════════════════════════════════════════


class TestCounter:
    """Tests for Counter metric."""

    def test_initial_zero(self):
        c = Counter("test_counter")
        assert c.value == 0.0

    def test_inc_default(self):
        c = Counter("test_counter")
        c.inc()
        assert c.value == 1.0

    def test_inc_custom_amount(self):
        c = Counter("test_counter")
        c.inc(5)
        assert c.value == 5.0

    def test_inc_multiple(self):
        c = Counter("test_counter")
        c.inc(3)
        c.inc(7)
        assert c.value == 10.0

    def test_inc_negative_raises(self):
        c = Counter("test_counter")
        with pytest.raises(ValueError):
            c.inc(-1)

    def test_reset(self):
        c = Counter("test_counter")
        c.inc(10)
        c.reset()
        assert c.value == 0.0

    def test_to_dict(self):
        c = Counter("requests_total", labels={"method": "GET"})
        c.inc(42)
        d = c.to_dict()
        assert d["name"] == "requests_total"
        assert d["type"] == "counter"
        assert d["value"] == 42.0
        assert d["labels"]["method"] == "GET"

    def test_name_and_labels(self):
        c = Counter("test", labels={"env": "prod"})
        assert c.name == "test"
        assert c.labels == {"env": "prod"}

    def test_thread_safety(self):
        c = Counter("concurrent")
        threads = []
        for _ in range(10):
            t = threading.Thread(target=lambda: [c.inc() for _ in range(100)])
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
        assert c.value == 1000.0


# ═══════════════════════════════════════════════════════════════════════════════
# GAUGE
# ═══════════════════════════════════════════════════════════════════════════════


class TestGauge:
    """Tests for Gauge metric."""

    def test_initial_zero(self):
        g = Gauge("test_gauge")
        assert g.value == 0.0

    def test_set(self):
        g = Gauge("test_gauge")
        g.set(42)
        assert g.value == 42.0

    def test_inc(self):
        g = Gauge("test_gauge")
        g.set(10)
        g.inc()
        assert g.value == 11.0

    def test_inc_custom(self):
        g = Gauge("test_gauge")
        g.inc(5)
        assert g.value == 5.0

    def test_dec(self):
        g = Gauge("test_gauge")
        g.set(10)
        g.dec()
        assert g.value == 9.0

    def test_dec_custom(self):
        g = Gauge("test_gauge")
        g.set(10)
        g.dec(3)
        assert g.value == 7.0

    def test_negative_value(self):
        g = Gauge("test_gauge")
        g.dec(5)
        assert g.value == -5.0

    def test_to_dict(self):
        g = Gauge("active_users")
        g.set(42)
        d = g.to_dict()
        assert d["name"] == "active_users"
        assert d["type"] == "gauge"
        assert d["value"] == 42.0


# ═══════════════════════════════════════════════════════════════════════════════
# HISTOGRAM
# ═══════════════════════════════════════════════════════════════════════════════


class TestHistogram:
    """Tests for Histogram metric."""

    def test_initial_empty(self):
        h = Histogram("test_hist")
        assert h.count == 0
        assert h.sum == 0.0
        assert h.avg == 0.0

    def test_observe_single(self):
        h = Histogram("test_hist")
        h.observe(42.0)
        assert h.count == 1
        assert h.sum == 42.0
        assert h.avg == 42.0

    def test_observe_multiple(self):
        h = Histogram("test_hist")
        h.observe(10)
        h.observe(20)
        h.observe(30)
        assert h.count == 3
        assert h.sum == 60.0
        assert h.avg == 20.0

    def test_min_max(self):
        h = Histogram("test_hist")
        h.observe(5)
        h.observe(100)
        h.observe(50)
        assert h.min == 5
        assert h.max == 100

    def test_min_max_empty(self):
        h = Histogram("test_hist")
        assert h.min == 0.0
        assert h.max == 0.0

    def test_percentile_p50(self):
        h = Histogram("test_hist")
        for i in range(1, 101):
            h.observe(i)
        p50 = h.percentile(0.5)
        assert 49 <= p50 <= 51

    def test_percentile_p95(self):
        h = Histogram("test_hist")
        for i in range(1, 101):
            h.observe(i)
        p95 = h.percentile(0.95)
        assert 94 <= p95 <= 96

    def test_percentile_empty(self):
        h = Histogram("test_hist")
        assert h.percentile(0.5) == 0.0

    def test_max_samples_bounded(self):
        h = Histogram("test_hist", max_samples=10)
        for i in range(100):
            h.observe(i)
        assert h.count == 100  # Total count
        # But internal buffer is bounded
        assert len(h._values) <= 10

    def test_to_dict(self):
        h = Histogram("latency_ms")
        h.observe(10)
        h.observe(20)
        d = h.to_dict()
        assert d["name"] == "latency_ms"
        assert d["type"] == "histogram"
        assert d["count"] == 2
        assert d["sum"] == 30.0
        assert "p50" in d
        assert "p95" in d
        assert "p99" in d


# ═══════════════════════════════════════════════════════════════════════════════
# TIMER
# ═══════════════════════════════════════════════════════════════════════════════


class TestTimer:
    """Tests for Timer metric."""

    def test_context_manager(self):
        timer = Timer("test_timer")
        with timer:
            time.sleep(0.01)
        assert timer.histogram.count == 1
        assert timer.histogram.avg > 0

    def test_manual_observe(self):
        timer = Timer("test_timer")
        timer.observe(42.5)
        assert timer.histogram.count == 1
        assert timer.histogram.avg == 42.5

    def test_multiple_measurements(self):
        timer = Timer("test_timer")
        timer.observe(10)
        timer.observe(20)
        timer.observe(30)
        assert timer.histogram.count == 3

    def test_to_dict(self):
        timer = Timer("call_ms")
        timer.observe(100)
        d = timer.to_dict()
        assert d["name"] == "call_ms"
        assert d["count"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# METRIC VALUE
# ═══════════════════════════════════════════════════════════════════════════════


class TestMetricValue:
    """Tests for MetricValue dataclass."""

    def test_creation(self):
        mv = MetricValue("test", MetricType.COUNTER, 42.0)
        assert mv.name == "test"
        assert mv.type == MetricType.COUNTER
        assert mv.value == 42.0
        assert mv.timestamp > 0

    def test_with_labels(self):
        mv = MetricValue("test", MetricType.GAUGE, 1.0,
                         labels={"host": "prod"})
        assert mv.labels["host"] == "prod"

    def test_metric_types(self):
        assert MetricType.COUNTER.value == "counter"
        assert MetricType.GAUGE.value == "gauge"
        assert MetricType.HISTOGRAM.value == "histogram"
        assert MetricType.TIMER.value == "timer"


# ═══════════════════════════════════════════════════════════════════════════════
# METRICS REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════


class TestMetricsRegistry:
    """Tests for MetricsRegistry."""

    def setup_method(self):
        self.registry = MetricsRegistry()

    def test_counter_creation(self):
        c = self.registry.counter("test")
        assert isinstance(c, Counter)
        assert c.name == "test"

    def test_counter_reuse(self):
        c1 = self.registry.counter("test")
        c2 = self.registry.counter("test")
        assert c1 is c2

    def test_gauge_creation(self):
        g = self.registry.gauge("test")
        assert isinstance(g, Gauge)

    def test_gauge_reuse(self):
        g1 = self.registry.gauge("test")
        g2 = self.registry.gauge("test")
        assert g1 is g2

    def test_histogram_creation(self):
        h = self.registry.histogram("test")
        assert isinstance(h, Histogram)

    def test_timer_creation(self):
        t = self.registry.timer("test")
        assert isinstance(t, Timer)

    def test_get_all(self):
        self.registry.counter("req").inc(10)
        self.registry.gauge("active").set(5)
        self.registry.histogram("latency").observe(42)
        self.registry.timer("call").observe(100)

        data = self.registry.get_all()
        assert "uptime_seconds" in data
        assert "counters" in data
        assert "gauges" in data
        assert "histograms" in data
        assert "timers" in data
        assert "req" in data["counters"]
        assert "active" in data["gauges"]

    def test_health_check_healthy(self):
        self.registry.counter("requests").inc(100)
        self.registry.counter("errors").inc(5)
        health = self.registry.health_check()
        assert health["status"] == "healthy"
        assert health["total_requests"] == 105
        assert health["total_errors"] == 5

    def test_health_check_degraded(self):
        self.registry.counter("errors").inc(60)
        self.registry.counter("requests").inc(40)
        health = self.registry.health_check()
        assert health["status"] == "degraded"

    def test_health_check_unhealthy(self):
        self.registry.counter("errors").inc(90)
        self.registry.counter("ok").inc(10)
        health = self.registry.health_check()
        assert health["status"] == "unhealthy"

    def test_health_check_no_requests(self):
        health = self.registry.health_check()
        assert health["status"] == "healthy"
        assert health["total_requests"] == 0

    def test_reset(self):
        self.registry.counter("test").inc(10)
        self.registry.reset()
        data = self.registry.get_all()
        assert data["counters"] == {}

    def test_uptime(self):
        time.sleep(0.05)
        data = self.registry.get_all()
        assert data["uptime_seconds"] >= 0.04


# ═══════════════════════════════════════════════════════════════════════════════
# SPAN
# ═══════════════════════════════════════════════════════════════════════════════


class TestSpan:
    """Tests for Span data model."""

    def test_creation(self):
        span = Span(span_id="abc", trace_id="xyz", name="test_op")
        assert span.span_id == "abc"
        assert span.trace_id == "xyz"
        assert span.name == "test_op"
        assert span.status == SpanStatus.OK

    def test_auto_start_time(self):
        span = Span(span_id="a", trace_id="t", name="op")
        assert span.start_time > 0

    def test_auto_span_id(self):
        span = Span(span_id="", trace_id="t", name="op")
        assert len(span.span_id) == 12

    def test_end(self):
        span = Span(span_id="a", trace_id="t", name="op")
        time.sleep(0.01)
        span.end()
        assert span.end_time > span.start_time
        assert span.duration_ms > 0

    def test_end_with_status(self):
        span = Span(span_id="a", trace_id="t", name="op")
        span.end(SpanStatus.ERROR)
        assert span.status == SpanStatus.ERROR

    def test_add_event(self):
        span = Span(span_id="a", trace_id="t", name="op")
        span.add_event("retry", attempt=2)
        assert len(span.events) == 1
        assert span.events[0]["name"] == "retry"
        assert span.events[0]["attributes"]["attempt"] == 2

    def test_set_attribute(self):
        span = Span(span_id="a", trace_id="t", name="op")
        span.set_attribute("model", "deepseek")
        assert span.attributes["model"] == "deepseek"

    def test_duration_while_running(self):
        span = Span(span_id="a", trace_id="t", name="op")
        # Duration while running (not ended)
        assert span.duration_ms >= 0

    def test_to_dict(self):
        span = Span(span_id="abc", trace_id="xyz", name="op")
        span.set_attribute("key", "val")
        span.end()
        d = span.to_dict()
        assert d["span_id"] == "abc"
        assert d["trace_id"] == "xyz"
        assert d["name"] == "op"
        assert d["status"] == "ok"
        assert "duration_ms" in d


# ═══════════════════════════════════════════════════════════════════════════════
# TRACE
# ═══════════════════════════════════════════════════════════════════════════════


class TestTrace:
    """Tests for Trace data model."""

    def test_creation(self):
        trace = Trace(trace_id="abc123")
        assert trace.trace_id == "abc123"
        assert trace.start_time > 0

    def test_auto_trace_id(self):
        trace = Trace(trace_id="")
        assert len(trace.trace_id) == 16

    def test_span_count(self):
        trace = Trace(trace_id="t")
        assert trace.span_count == 0
        trace.spans.append(Span(span_id="s1", trace_id="t", name="op1"))
        assert trace.span_count == 1

    def test_error_count(self):
        trace = Trace(trace_id="t")
        s1 = Span(span_id="s1", trace_id="t", name="ok_op")
        s2 = Span(span_id="s2", trace_id="t", name="err_op")
        s2.end(SpanStatus.ERROR)
        trace.spans.extend([s1, s2])
        assert trace.error_count == 1
        assert trace.has_errors is True

    def test_no_errors(self):
        trace = Trace(trace_id="t")
        trace.spans.append(Span(span_id="s1", trace_id="t", name="op"))
        assert trace.has_errors is False

    def test_end(self):
        trace = Trace(trace_id="t")
        time.sleep(0.01)
        trace.end()
        assert trace.end_time > trace.start_time

    def test_to_dict(self):
        trace = Trace(trace_id="t", user_id=123)
        trace.end()
        d = trace.to_dict()
        assert d["trace_id"] == "t"
        assert d["user_id"] == 123
        assert "duration_ms" in d

    def test_summary(self):
        trace = Trace(trace_id="t", user_id=123)
        trace.end()
        s = trace.summary()
        assert s["trace_id"] == "t"
        assert s["user_id"] == 123
        assert s["spans"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# TRACE CONTEXT
# ═══════════════════════════════════════════════════════════════════════════════


class TestTraceContext:
    """Tests for TraceContext."""

    def setup_method(self):
        self.ctx = TraceContext()

    def test_no_active_trace(self):
        assert self.ctx.active_trace is None
        assert self.ctx.active_span is None

    def test_start_trace(self):
        trace = self.ctx.start_trace(user_id=1)
        assert isinstance(trace, Trace)
        assert self.ctx.active_trace is trace

    def test_start_span(self):
        self.ctx.start_trace()
        span = self.ctx.start_span("test_op")
        assert isinstance(span, Span)
        assert self.ctx.active_span is span

    def test_nested_spans(self):
        self.ctx.start_trace()
        outer = self.ctx.start_span("outer")
        inner = self.ctx.start_span("inner")
        assert inner.parent_id == outer.span_id
        assert self.ctx.active_span is inner

    def test_end_span(self):
        self.ctx.start_trace()
        self.ctx.start_span("op")
        span = self.ctx.end_span()
        assert span.end_time > 0
        assert self.ctx.active_span is None

    def test_end_span_nested(self):
        self.ctx.start_trace()
        outer = self.ctx.start_span("outer")
        self.ctx.start_span("inner")
        self.ctx.end_span()  # ends inner
        assert self.ctx.active_span is outer

    def test_end_trace(self):
        self.ctx.start_trace()
        self.ctx.start_span("op")
        self.ctx.end_span()
        trace = self.ctx.end_trace()
        assert trace is not None
        assert trace.end_time > 0
        assert self.ctx.active_trace is None

    def test_auto_trace_on_span(self):
        """If no trace is active, start_span auto-creates one."""
        span = self.ctx.start_span("auto")
        assert self.ctx.active_trace is not None
        assert span.trace_id == self.ctx.active_trace.trace_id

    def test_end_span_empty(self):
        result = self.ctx.end_span()
        assert result is None

    def test_end_trace_empty(self):
        result = self.ctx.end_trace()
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# REQUEST TRACER
# ═══════════════════════════════════════════════════════════════════════════════


class TestRequestTracer:
    """Tests for RequestTracer."""

    def setup_method(self):
        self.tracer = RequestTracer()

    def test_start_request(self):
        trace = self.tracer.start_request(user_id=123, message="Hello")
        assert isinstance(trace, Trace)
        assert trace.user_id == 123
        assert trace.metadata["message_preview"] == "Hello"

    def test_span_context_manager(self):
        self.tracer.start_request(user_id=1)
        with self.tracer.span("test_op", key="val") as span:
            assert isinstance(span, Span)
            assert span.name == "test_op"
        self.tracer.end_request()

    def test_end_request(self):
        self.tracer.start_request(user_id=1)
        trace = self.tracer.end_request()
        assert trace is not None
        assert trace.end_time > 0

    def test_recent_traces(self):
        for i in range(5):
            self.tracer.start_request(user_id=i)
            self.tracer.end_request()

        recent = self.tracer.get_recent_traces(3)
        assert len(recent) == 3

    def test_get_trace_by_id(self):
        self.tracer.start_request(user_id=1)
        trace = self.tracer.end_request()
        found = self.tracer.get_trace_by_id(trace.trace_id)
        assert found is not None
        assert found["trace_id"] == trace.trace_id

    def test_get_trace_by_id_not_found(self):
        assert self.tracer.get_trace_by_id("nonexistent") is None

    def test_get_stats(self):
        self.tracer.start_request(user_id=1)
        self.tracer.end_request()
        stats = self.tracer.get_stats()
        assert stats["total_requests"] == 1
        assert stats["total_errors"] == 0

    def test_error_tracking(self):
        self.tracer.start_request(user_id=1)
        with self.tracer.span("failing"):
            pass  # no error
        trace = self.tracer.end_request()
        assert not trace.has_errors

    def test_error_in_span(self):
        self.tracer.start_request(user_id=1)
        try:
            with self.tracer.span("failing"):
                raise ValueError("test error")
        except ValueError:
            pass
        trace = self.tracer.end_request()
        assert trace.has_errors

    def test_reset(self):
        self.tracer.start_request(user_id=1)
        self.tracer.end_request()
        self.tracer.reset()
        stats = self.tracer.get_stats()
        assert stats["total_requests"] == 0

    def test_max_traces_bounded(self):
        tracer = RequestTracer(max_traces=5)
        for i in range(20):
            tracer.start_request(user_id=i)
            tracer.end_request()
        assert len(tracer._traces) <= 5

    def test_message_preview_truncated(self):
        long_msg = "A" * 200
        self.tracer.start_request(user_id=1, message=long_msg)
        trace = self.tracer.context.active_trace
        assert len(trace.metadata["message_preview"]) == 100

    def test_properties(self):
        assert isinstance(self.tracer.context, TraceContext)

    def test_stats_avg_duration(self):
        for _ in range(3):
            self.tracer.start_request(user_id=1)
            time.sleep(0.01)
            self.tracer.end_request()
        stats = self.tracer.get_stats()
        assert stats["avg_duration_ms"] > 0


# ═══════════════════════════════════════════════════════════════════════════════
# SPAN STATUS
# ═══════════════════════════════════════════════════════════════════════════════


class TestSpanStatus:
    """Tests for SpanStatus enum."""

    def test_values(self):
        assert SpanStatus.OK.value == "ok"
        assert SpanStatus.ERROR.value == "error"
        assert SpanStatus.TIMEOUT.value == "timeout"
        assert SpanStatus.CANCELLED.value == "cancelled"


# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL INSTANCES
# ═══════════════════════════════════════════════════════════════════════════════


class TestGlobalInstances:
    """Tests for global singleton instances."""

    def test_metrics_registry_exists(self):
        assert metrics_registry is not None
        assert isinstance(metrics_registry, MetricsRegistry)

    def test_request_tracer_exists(self):
        assert request_tracer is not None
        assert isinstance(request_tracer, RequestTracer)

    def test_metrics_registry_functional(self):
        c = metrics_registry.counter("test_global_counter")
        c.inc()
        assert c.value >= 1.0

    def test_request_tracer_functional(self):
        trace = request_tracer.start_request(user_id=99998)
        request_tracer.end_request()
        assert trace is not None
