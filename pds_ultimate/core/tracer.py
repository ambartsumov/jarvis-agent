"""
PDS-Ultimate Request Tracer
==============================
Step 10: Distributed-style request tracing for observability.

Tracks the full lifecycle of a request through the agent pipeline:
  Message → EQ Analysis → Mode Selection → Planning → Tool Calls → Response

No external dependencies — pure Python implementation.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pds_ultimate.config import logger

# ═══════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════


class SpanStatus(str, Enum):
    """Status of a trace span."""
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class Span:
    """
    A single operation within a trace.

    Modeled after OpenTelemetry spans but simplified.
    """
    span_id: str
    trace_id: str
    name: str
    parent_id: str | None = None
    start_time: float = 0.0
    end_time: float = 0.0
    status: SpanStatus = SpanStatus.OK
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        if self.start_time == 0.0:
            self.start_time = time.time()
        if not self.span_id:
            self.span_id = uuid.uuid4().hex[:12]

    @property
    def duration_ms(self) -> float:
        """Duration in milliseconds."""
        if self.end_time == 0.0:
            return (time.time() - self.start_time) * 1000
        return (self.end_time - self.start_time) * 1000

    def end(self, status: SpanStatus = SpanStatus.OK) -> None:
        """End the span."""
        self.end_time = time.time()
        self.status = status

    def add_event(self, name: str, **attributes) -> None:
        """Add an event to the span."""
        self.events.append({
            "name": name,
            "timestamp": time.time(),
            "attributes": attributes,
        })

    def set_attribute(self, key: str, value: Any) -> None:
        """Set a span attribute."""
        self.attributes[key] = value

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "name": self.name,
            "parent_id": self.parent_id,
            "start_time": self.start_time,
            "duration_ms": round(self.duration_ms, 2),
            "status": self.status.value,
            "attributes": self.attributes,
            "events": self.events,
        }


@dataclass
class Trace:
    """
    A complete request trace containing multiple spans.
    """
    trace_id: str
    user_id: int = 0
    start_time: float = 0.0
    end_time: float = 0.0
    spans: list[Span] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.trace_id:
            self.trace_id = uuid.uuid4().hex[:16]
        if self.start_time == 0.0:
            self.start_time = time.time()

    @property
    def duration_ms(self) -> float:
        if self.end_time == 0.0:
            return (time.time() - self.start_time) * 1000
        return (self.end_time - self.start_time) * 1000

    @property
    def span_count(self) -> int:
        return len(self.spans)

    @property
    def error_count(self) -> int:
        return sum(1 for s in self.spans if s.status == SpanStatus.ERROR)

    @property
    def has_errors(self) -> bool:
        return self.error_count > 0

    def end(self) -> None:
        """End the trace."""
        self.end_time = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "user_id": self.user_id,
            "duration_ms": round(self.duration_ms, 2),
            "span_count": self.span_count,
            "error_count": self.error_count,
            "spans": [s.to_dict() for s in self.spans],
            "metadata": self.metadata,
        }

    def summary(self) -> dict[str, Any]:
        """Short summary for logging."""
        return {
            "trace_id": self.trace_id,
            "user_id": self.user_id,
            "duration_ms": round(self.duration_ms, 2),
            "spans": self.span_count,
            "errors": self.error_count,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# TRACE CONTEXT — Active trace management
# ═══════════════════════════════════════════════════════════════════════════════


class TraceContext:
    """
    Manages the active trace for the current request.
    Thread-local storage for trace propagation.

    Usage:
        ctx = TraceContext()
        trace = ctx.start_trace(user_id=123)
        span = ctx.start_span("llm_call")
        # ... do work ...
        span.end()
        trace.end()
    """

    def __init__(self):
        self._local = threading.local()

    @property
    def active_trace(self) -> Trace | None:
        """Get the active trace for the current thread."""
        return getattr(self._local, "trace", None)

    @property
    def active_span(self) -> Span | None:
        """Get the active span for the current thread."""
        stack = getattr(self._local, "span_stack", [])
        return stack[-1] if stack else None

    def start_trace(
        self,
        user_id: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> Trace:
        """Start a new trace."""
        trace = Trace(
            trace_id=uuid.uuid4().hex[:16],
            user_id=user_id,
            metadata=metadata or {},
        )
        self._local.trace = trace
        self._local.span_stack = []
        return trace

    def start_span(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
    ) -> Span:
        """
        Start a new span within the active trace.

        Args:
            name: Operation name (e.g., "llm_call", "tool_execute")
            attributes: Optional span attributes

        Returns:
            Span object (call .end() when done)
        """
        trace = self.active_trace
        if trace is None:
            # Auto-create trace if none active
            trace = self.start_trace()

        parent = self.active_span
        span = Span(
            span_id=uuid.uuid4().hex[:12],
            trace_id=trace.trace_id,
            name=name,
            parent_id=parent.span_id if parent else None,
            attributes=attributes or {},
        )
        trace.spans.append(span)

        # Push onto span stack
        if not hasattr(self._local, "span_stack"):
            self._local.span_stack = []
        self._local.span_stack.append(span)

        return span

    def end_span(self, status: SpanStatus = SpanStatus.OK) -> Span | None:
        """End the current active span."""
        stack = getattr(self._local, "span_stack", [])
        if not stack:
            return None
        span = stack.pop()
        span.end(status)
        return span

    def end_trace(self) -> Trace | None:
        """End the current active trace."""
        trace = self.active_trace
        if trace is None:
            return None
        trace.end()
        self._local.trace = None
        self._local.span_stack = []
        return trace


# ═══════════════════════════════════════════════════════════════════════════════
# REQUEST TRACER — High-level API
# ═══════════════════════════════════════════════════════════════════════════════


class RequestTracer:
    """
    High-level request tracing API.

    Maintains a ring buffer of recent traces for inspection.
    Thread-safe.

    Usage:
        tracer = RequestTracer()

        # Start tracing a request
        trace = tracer.start_request(user_id=123, message="Привет")

        # Create spans for operations
        with tracer.span("eq_analysis") as span:
            span.set_attribute("emotion", "joy")

        with tracer.span("llm_call") as span:
            span.set_attribute("model", "deepseek-chat")

        # End request
        tracer.end_request()

        # Inspect recent traces
        print(tracer.get_recent_traces(5))
    """

    MAX_TRACES = 200

    def __init__(self, max_traces: int = MAX_TRACES):
        self._context = TraceContext()
        self._traces: deque[Trace] = deque(maxlen=max_traces)
        self._lock = threading.Lock()
        self._total_requests: int = 0
        self._total_errors: int = 0

    @property
    def context(self) -> TraceContext:
        return self._context

    def start_request(
        self,
        user_id: int = 0,
        message: str = "",
    ) -> Trace:
        """
        Start tracing a new request.

        Args:
            user_id: Telegram user ID
            message: First N chars of user message (for debugging)
        """
        metadata = {}
        if message:
            metadata["message_preview"] = message[:100]

        trace = self._context.start_trace(
            user_id=user_id,
            metadata=metadata,
        )

        with self._lock:
            self._total_requests += 1

        return trace

    def span(self, name: str, **attributes) -> SpanContextManager:
        """
        Create a span as a context manager.

        Usage:
            with tracer.span("operation", key="value") as s:
                # ... work ...
                s.set_attribute("result", "ok")
        """
        return SpanContextManager(self._context, name, attributes)

    def end_request(self) -> Trace | None:
        """End the current request trace and archive it."""
        trace = self._context.end_trace()
        if trace is not None:
            with self._lock:
                self._traces.append(trace)
                if trace.has_errors:
                    self._total_errors += 1

            logger.debug(
                f"Trace[{trace.trace_id}]: "
                f"{trace.duration_ms:.0f}ms, "
                f"{trace.span_count} spans, "
                f"{trace.error_count} errors"
            )
        return trace

    def get_recent_traces(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent traces as dicts."""
        with self._lock:
            traces = list(self._traces)
        return [t.summary() for t in traces[-limit:]]

    def get_trace_by_id(self, trace_id: str) -> dict[str, Any] | None:
        """Find a trace by ID."""
        with self._lock:
            for trace in self._traces:
                if trace.trace_id == trace_id:
                    return trace.to_dict()
        return None

    def get_stats(self) -> dict[str, Any]:
        """Get tracer statistics."""
        with self._lock:
            traces = list(self._traces)
            total = self._total_requests
            errors = self._total_errors

        durations = [t.duration_ms for t in traces if t.end_time > 0]
        avg_duration = (
            sum(durations) / len(durations) if durations else 0.0
        )

        return {
            "total_requests": total,
            "total_errors": errors,
            "error_rate": round(errors / max(1, total), 4),
            "avg_duration_ms": round(avg_duration, 2),
            "traces_in_buffer": len(traces),
        }

    def reset(self) -> None:
        """Reset all traces (for testing)."""
        with self._lock:
            self._traces.clear()
            self._total_requests = 0
            self._total_errors = 0


# ═══════════════════════════════════════════════════════════════════════════════
# SPAN CONTEXT MANAGER
# ═══════════════════════════════════════════════════════════════════════════════


class SpanContextManager:
    """Context manager for spans in RequestTracer."""

    __slots__ = ("_context", "_name", "_attributes", "_span")

    def __init__(
        self,
        context: TraceContext,
        name: str,
        attributes: dict[str, Any],
    ):
        self._context = context
        self._name = name
        self._attributes = attributes
        self._span: Span | None = None

    def __enter__(self) -> Span:
        self._span = self._context.start_span(
            self._name, self._attributes
        )
        return self._span

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None:
            status = SpanStatus.ERROR
            if self._span:
                self._span.add_event(
                    "error",
                    error_type=exc_type.__name__,
                    error_message=str(exc_val),
                )
        else:
            status = SpanStatus.OK
        self._context.end_span(status)


# ─── Global instance ────────────────────────────────────────────────────────

request_tracer = RequestTracer()
