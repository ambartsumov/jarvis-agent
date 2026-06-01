"""
PDS-Ultimate Metrics Collector
================================
Step 10: Internal metrics collection for observability.

Lightweight, in-process metrics without external dependencies.
Supports counters, gauges, histograms, and timers.

Design principles:
- Zero external dependencies (no prometheus, no statsd)
- Thread-safe via simple locking
- Bounded memory via ring buffers
- JSON-serializable for /stats endpoint
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ═══════════════════════════════════════════════════════════════════════════════
# METRIC TYPES
# ═══════════════════════════════════════════════════════════════════════════════


class MetricType(str, Enum):
    """Types of metrics."""
    COUNTER = "counter"          # Monotonically increasing
    GAUGE = "gauge"              # Point-in-time value
    HISTOGRAM = "histogram"      # Distribution of values
    TIMER = "timer"              # Duration measurements


@dataclass
class MetricValue:
    """Single metric data point."""
    name: str
    type: MetricType
    value: float
    timestamp: float = 0.0
    labels: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


# ═══════════════════════════════════════════════════════════════════════════════
# COUNTER
# ═══════════════════════════════════════════════════════════════════════════════


class Counter:
    """
    Monotonically increasing counter.
    Thread-safe.

    Usage:
        counter = Counter("requests_total")
        counter.inc()
        counter.inc(5)
    """

    __slots__ = ("name", "labels", "_value", "_lock")

    def __init__(self, name: str, labels: dict[str, str] | None = None):
        self.name = name
        self.labels = labels or {}
        self._value: float = 0.0
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0) -> None:
        """Increment counter by amount (must be non-negative)."""
        if amount < 0:
            raise ValueError("Counter can only be incremented")
        with self._lock:
            self._value += amount

    @property
    def value(self) -> float:
        with self._lock:
            return self._value

    def reset(self) -> None:
        """Reset counter to 0 (for testing only)."""
        with self._lock:
            self._value = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": MetricType.COUNTER.value,
            "value": self.value,
            "labels": self.labels,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# GAUGE
# ═══════════════════════════════════════════════════════════════════════════════


class Gauge:
    """
    Point-in-time value that can go up and down.
    Thread-safe.

    Usage:
        gauge = Gauge("active_requests")
        gauge.set(5)
        gauge.inc()
        gauge.dec()
    """

    __slots__ = ("name", "labels", "_value", "_lock")

    def __init__(self, name: str, labels: dict[str, str] | None = None):
        self.name = name
        self.labels = labels or {}
        self._value: float = 0.0
        self._lock = threading.Lock()

    def set(self, value: float) -> None:
        """Set gauge to a specific value."""
        with self._lock:
            self._value = value

    def inc(self, amount: float = 1.0) -> None:
        """Increment gauge."""
        with self._lock:
            self._value += amount

    def dec(self, amount: float = 1.0) -> None:
        """Decrement gauge."""
        with self._lock:
            self._value -= amount

    @property
    def value(self) -> float:
        with self._lock:
            return self._value

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": MetricType.GAUGE.value,
            "value": self.value,
            "labels": self.labels,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# HISTOGRAM
# ═══════════════════════════════════════════════════════════════════════════════


class Histogram:
    """
    Distribution of values with percentile computation.
    Uses ring buffer to bound memory.

    Usage:
        hist = Histogram("response_time_ms", max_samples=1000)
        hist.observe(42.5)
        print(hist.percentile(0.95))
    """

    DEFAULT_MAX_SAMPLES = 1000

    __slots__ = ("name", "labels", "_values", "_count", "_sum", "_lock")

    def __init__(
        self,
        name: str,
        labels: dict[str, str] | None = None,
        max_samples: int = DEFAULT_MAX_SAMPLES,
    ):
        self.name = name
        self.labels = labels or {}
        self._values: deque[float] = deque(maxlen=max_samples)
        self._count: int = 0
        self._sum: float = 0.0
        self._lock = threading.Lock()

    def observe(self, value: float) -> None:
        """Record a value in the histogram."""
        with self._lock:
            self._values.append(value)
            self._count += 1
            self._sum += value

    @property
    def count(self) -> int:
        with self._lock:
            return self._count

    @property
    def sum(self) -> float:
        with self._lock:
            return self._sum

    @property
    def avg(self) -> float:
        with self._lock:
            return self._sum / max(1, self._count)

    def percentile(self, p: float) -> float:
        """
        Compute percentile (0.0-1.0).

        Args:
            p: Percentile between 0.0 and 1.0 (e.g., 0.95 for P95)

        Returns:
            Percentile value, or 0.0 if no data
        """
        with self._lock:
            if not self._values:
                return 0.0
            sorted_vals = sorted(self._values)
            idx = int(p * (len(sorted_vals) - 1))
            return sorted_vals[idx]

    @property
    def min(self) -> float:
        with self._lock:
            return min(self._values) if self._values else 0.0

    @property
    def max(self) -> float:
        with self._lock:
            return max(self._values) if self._values else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": MetricType.HISTOGRAM.value,
            "count": self.count,
            "sum": round(self.sum, 2),
            "avg": round(self.avg, 2),
            "min": round(self.min, 2),
            "max": round(self.max, 2),
            "p50": round(self.percentile(0.5), 2),
            "p95": round(self.percentile(0.95), 2),
            "p99": round(self.percentile(0.99), 2),
            "labels": self.labels,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# TIMER (context manager over Histogram)
# ═══════════════════════════════════════════════════════════════════════════════


class Timer:
    """
    Context manager for timing operations.
    Records durations in an underlying Histogram.

    Usage:
        timer = Timer("llm_call_ms")
        with timer:
            result = call_llm()
        print(timer.histogram.avg)
    """

    __slots__ = ("_histogram", "_start")

    def __init__(
        self,
        name: str,
        labels: dict[str, str] | None = None,
        max_samples: int = Histogram.DEFAULT_MAX_SAMPLES,
    ):
        self._histogram = Histogram(name, labels, max_samples)
        self._start: float = 0.0

    @property
    def histogram(self) -> Histogram:
        return self._histogram

    def __enter__(self) -> "Timer":
        self._start = time.monotonic()
        return self

    def __exit__(self, *args) -> None:
        elapsed_ms = (time.monotonic() - self._start) * 1000
        self._histogram.observe(elapsed_ms)

    def observe(self, duration_ms: float) -> None:
        """Manually record a duration."""
        self._histogram.observe(duration_ms)

    def to_dict(self) -> dict[str, Any]:
        return self._histogram.to_dict()


# ═══════════════════════════════════════════════════════════════════════════════
# METRICS REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════


class MetricsRegistry:
    """
    Central registry for all metrics.
    Thread-safe singleton pattern.

    Usage:
        registry = MetricsRegistry()
        counter = registry.counter("requests_total")
        gauge = registry.gauge("active_users")
        histogram = registry.histogram("response_time_ms")
        timer = registry.timer("llm_call_ms")
    """

    def __init__(self):
        self._counters: dict[str, Counter] = {}
        self._gauges: dict[str, Gauge] = {}
        self._histograms: dict[str, Histogram] = {}
        self._timers: dict[str, Timer] = {}
        self._lock = threading.Lock()
        self._start_time = time.time()

    def counter(
        self, name: str, labels: dict[str, str] | None = None
    ) -> Counter:
        """Get or create a counter."""
        with self._lock:
            if name not in self._counters:
                self._counters[name] = Counter(name, labels)
            return self._counters[name]

    def gauge(
        self, name: str, labels: dict[str, str] | None = None
    ) -> Gauge:
        """Get or create a gauge."""
        with self._lock:
            if name not in self._gauges:
                self._gauges[name] = Gauge(name, labels)
            return self._gauges[name]

    def histogram(
        self,
        name: str,
        labels: dict[str, str] | None = None,
        max_samples: int = Histogram.DEFAULT_MAX_SAMPLES,
    ) -> Histogram:
        """Get or create a histogram."""
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = Histogram(name, labels, max_samples)
            return self._histograms[name]

    def timer(
        self,
        name: str,
        labels: dict[str, str] | None = None,
        max_samples: int = Histogram.DEFAULT_MAX_SAMPLES,
    ) -> Timer:
        """Get or create a timer."""
        with self._lock:
            if name not in self._timers:
                self._timers[name] = Timer(name, labels, max_samples)
            return self._timers[name]

    def get_all(self) -> dict[str, Any]:
        """Get all metrics as a JSON-serializable dict."""
        with self._lock:
            result: dict[str, Any] = {
                "uptime_seconds": round(time.time() - self._start_time, 1),
                "counters": {
                    name: c.to_dict() for name, c in self._counters.items()
                },
                "gauges": {
                    name: g.to_dict() for name, g in self._gauges.items()
                },
                "histograms": {
                    name: h.to_dict() for name, h in self._histograms.items()
                },
                "timers": {
                    name: t.to_dict() for name, t in self._timers.items()
                },
            }
            return result

    def health_check(self) -> dict[str, Any]:
        """
        Get a health check summary.

        Returns:
            dict with status, uptime, and key metrics
        """
        uptime = time.time() - self._start_time
        with self._lock:
            total_requests = sum(
                c.value for c in self._counters.values()
            )
            total_errors = sum(
                c.value for name, c in self._counters.items()
                if "error" in name.lower()
            )

        error_rate = total_errors / max(1, total_requests)

        status = "healthy"
        if error_rate > 0.5:
            status = "degraded"
        if error_rate > 0.8:
            status = "unhealthy"

        return {
            "status": status,
            "uptime_seconds": round(uptime, 1),
            "total_requests": total_requests,
            "total_errors": total_errors,
            "error_rate": round(error_rate, 4),
            "metrics_count": (
                len(self._counters)
                + len(self._gauges)
                + len(self._histograms)
                + len(self._timers)
            ),
        }

    def reset(self) -> None:
        """Reset all metrics (for testing)."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
            self._timers.clear()
            self._start_time = time.time()


# ─── Global instance ────────────────────────────────────────────────────────

metrics_registry = MetricsRegistry()
