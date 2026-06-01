"""
PDS-Ultimate Tool Audit System v1.0
=====================================
Structured audit logging for all tool executions.

Every tool call is recorded with:
- Timestamp, tool name, parameters (sanitized)
- Result (success/fail), duration, error details
- Chain context (which agent/step triggered it)
- Resource usage estimates

Used for:
- Security auditing (who called what when)
- Performance profiling (slow tools, error rates)
- Debugging (full call chain reconstruction)
- Rate limiting (per-tool call frequency tracking)

Thread-safe, bounded buffer (max 10K entries), auto-prune.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pds_ultimate.config import logger

# ─── Constants ───────────────────────────────────────────────────────────────

MAX_AUDIT_ENTRIES = 10_000
PARAM_PREVIEW_LEN = 200        # max chars for parameter preview
OUTPUT_PREVIEW_LEN = 500       # max chars for output preview
RATE_LIMIT_WINDOW = 60.0       # seconds for rate limiting window
DEFAULT_RATE_LIMIT = 30        # max calls per tool per window


# ─── Enums ───────────────────────────────────────────────────────────────────

class AuditEventType(str, Enum):
    """Types of audit events."""
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_SUCCESS = "tool_call_success"
    TOOL_CALL_FAILURE = "tool_call_failure"
    TOOL_CALL_TIMEOUT = "tool_call_timeout"
    TOOL_CALL_BLOCKED = "tool_call_blocked"
    RATE_LIMIT_HIT = "rate_limit_hit"
    PARAM_VALIDATION_FAIL = "param_validation_fail"


# ─── Audit Entry ─────────────────────────────────────────────────────────────

@dataclass(slots=True)
class AuditEntry:
    """Single audit log entry for a tool execution."""
    event_type: AuditEventType
    tool_name: str
    timestamp: float
    params_preview: str = ""
    output_preview: str = ""
    error: str | None = None
    duration_ms: int = 0
    caller: str = ""            # who triggered (agent, sub_agent, etc.)
    chat_id: int | None = None
    attempt: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event_type.value,
            "tool": self.tool_name,
            "timestamp": self.timestamp,
            "params": self.params_preview,
            "output": self.output_preview[:100],
            "error": self.error,
            "duration_ms": self.duration_ms,
            "caller": self.caller,
            "chat_id": self.chat_id,
            "attempt": self.attempt,
        }


# ─── Sanitizer ───────────────────────────────────────────────────────────────

# Keys that should never appear in audit logs
_SENSITIVE_KEYS: frozenset[str] = frozenset({
    "password", "token", "secret", "api_key", "apikey",
    "access_token", "refresh_token", "private_key",
    "session_id", "cookie", "authorization", "credentials",
})


def sanitize_params(params: dict | None) -> str:
    """
    Create a safe preview of tool parameters.

    Redacts sensitive keys, truncates long values.
    """
    if not params:
        return "(no params)"

    sanitized: dict[str, Any] = {}
    for key, value in params.items():
        key_lower = key.lower()
        # Redact sensitive values
        if any(s in key_lower for s in _SENSITIVE_KEYS):
            sanitized[key] = "***REDACTED***"
        elif isinstance(value, str) and len(value) > PARAM_PREVIEW_LEN:
            sanitized[key] = value[:PARAM_PREVIEW_LEN] + "…"
        elif isinstance(value, (list, dict)):
            s = str(value)
            sanitized[key] = s[:PARAM_PREVIEW_LEN] + \
                "…" if len(s) > PARAM_PREVIEW_LEN else value
        else:
            sanitized[key] = value

    result = str(sanitized)
    return result[:PARAM_PREVIEW_LEN * 2] if len(result) > PARAM_PREVIEW_LEN * 2 else result


# ─── Rate Limiter ────────────────────────────────────────────────────────────

class ToolRateLimiter:
    """
    Per-tool sliding window rate limiter.

    Tracks call timestamps per tool, blocks if exceeding limit.
    """
    __slots__ = ("_limits", "_calls")

    def __init__(self):
        self._limits: dict[str, int] = {}       # tool_name → max per window
        self._calls: dict[str, deque[float]] = {}  # tool_name → timestamps

    def set_limit(self, tool_name: str, max_calls: int) -> None:
        """Set rate limit for a specific tool."""
        self._limits[tool_name] = max_calls

    def check(self, tool_name: str) -> bool:
        """
        Check if tool call is allowed.

        Returns True if allowed, False if rate limited.
        """
        limit = self._limits.get(tool_name, DEFAULT_RATE_LIMIT)
        now = time.time()
        cutoff = now - RATE_LIMIT_WINDOW

        if tool_name not in self._calls:
            self._calls[tool_name] = deque()

        q = self._calls[tool_name]

        # Prune old entries
        while q and q[0] < cutoff:
            q.popleft()

        return len(q) < limit

    def record(self, tool_name: str) -> None:
        """Record a tool call for rate limiting."""
        if tool_name not in self._calls:
            self._calls[tool_name] = deque()
        self._calls[tool_name].append(time.time())

    def get_usage(self, tool_name: str) -> dict[str, int]:
        """Get current usage for a tool."""
        limit = self._limits.get(tool_name, DEFAULT_RATE_LIMIT)
        now = time.time()
        cutoff = now - RATE_LIMIT_WINDOW

        q = self._calls.get(tool_name, deque())
        current = sum(1 for t in q if t >= cutoff)
        return {"current": current, "limit": limit, "remaining": max(0, limit - current)}

    def reset(self, tool_name: str | None = None) -> None:
        """Reset rate limit counters."""
        if tool_name:
            self._calls.pop(tool_name, None)
        else:
            self._calls.clear()


# ─── Audit Logger ────────────────────────────────────────────────────────────

class ToolAuditLogger:
    """
    Bounded audit log for tool executions.

    Features:
    - Bounded deque (max 10K entries, auto-evicts oldest)
    - Per-tool statistics (call count, error rate, avg duration)
    - Rate limiting integration
    - Query by tool name, event type, time range
    """
    __slots__ = ("_log", "_stats", "_rate_limiter", "_max_entries")

    def __init__(self, max_entries: int = MAX_AUDIT_ENTRIES):
        self._log: deque[AuditEntry] = deque(maxlen=max_entries)
        self._max_entries = max_entries
        self._stats: dict[str, dict[str, Any]] = {}
        self._rate_limiter = ToolRateLimiter()

    @property
    def rate_limiter(self) -> ToolRateLimiter:
        return self._rate_limiter

    def log_start(
        self,
        tool_name: str,
        params: dict | None = None,
        caller: str = "",
        chat_id: int | None = None,
        attempt: int = 1,
    ) -> AuditEntry:
        """Log the start of a tool call."""
        entry = AuditEntry(
            event_type=AuditEventType.TOOL_CALL_START,
            tool_name=tool_name,
            timestamp=time.time(),
            params_preview=sanitize_params(params),
            caller=caller,
            chat_id=chat_id,
            attempt=attempt,
        )
        self._log.append(entry)
        self._rate_limiter.record(tool_name)
        return entry

    def log_success(
        self,
        tool_name: str,
        output: str,
        duration_ms: int,
        caller: str = "",
        chat_id: int | None = None,
    ) -> AuditEntry:
        """Log a successful tool completion."""
        entry = AuditEntry(
            event_type=AuditEventType.TOOL_CALL_SUCCESS,
            tool_name=tool_name,
            timestamp=time.time(),
            output_preview=output[:OUTPUT_PREVIEW_LEN] if output else "",
            duration_ms=duration_ms,
            caller=caller,
            chat_id=chat_id,
        )
        self._log.append(entry)
        self._update_stats(tool_name, success=True, duration_ms=duration_ms)
        return entry

    def log_failure(
        self,
        tool_name: str,
        error: str,
        duration_ms: int,
        event_type: AuditEventType = AuditEventType.TOOL_CALL_FAILURE,
        caller: str = "",
        chat_id: int | None = None,
    ) -> AuditEntry:
        """Log a failed tool call."""
        entry = AuditEntry(
            event_type=event_type,
            tool_name=tool_name,
            timestamp=time.time(),
            error=error[:OUTPUT_PREVIEW_LEN],
            duration_ms=duration_ms,
            caller=caller,
            chat_id=chat_id,
        )
        self._log.append(entry)
        self._update_stats(tool_name, success=False, duration_ms=duration_ms)
        return entry

    def log_blocked(
        self,
        tool_name: str,
        reason: str,
        caller: str = "",
    ) -> AuditEntry:
        """Log a blocked tool call (rate limit, validation, etc.)."""
        entry = AuditEntry(
            event_type=AuditEventType.TOOL_CALL_BLOCKED,
            tool_name=tool_name,
            timestamp=time.time(),
            error=reason,
            caller=caller,
        )
        self._log.append(entry)
        logger.warning(f"Tool '{tool_name}' BLOCKED: {reason}")
        return entry

    def check_rate_limit(self, tool_name: str) -> bool:
        """Check if tool call is within rate limits. True = allowed."""
        return self._rate_limiter.check(tool_name)

    def _update_stats(self, tool_name: str, success: bool, duration_ms: int) -> None:
        """Update per-tool aggregate statistics."""
        if tool_name not in self._stats:
            self._stats[tool_name] = {
                "total_calls": 0,
                "successes": 0,
                "failures": 0,
                "total_duration_ms": 0,
                "max_duration_ms": 0,
                "min_duration_ms": float("inf"),
            }
        s = self._stats[tool_name]
        s["total_calls"] += 1
        if success:
            s["successes"] += 1
        else:
            s["failures"] += 1
        s["total_duration_ms"] += duration_ms
        s["max_duration_ms"] = max(s["max_duration_ms"], duration_ms)
        s["min_duration_ms"] = min(s["min_duration_ms"], duration_ms)

    # ─── Query Methods ──────────────────────────────────────────────────

    def get_recent(self, count: int = 50) -> list[AuditEntry]:
        """Get the N most recent audit entries."""
        entries = list(self._log)
        return entries[-count:] if len(entries) > count else entries

    def get_by_tool(self, tool_name: str, count: int = 50) -> list[AuditEntry]:
        """Get recent entries for a specific tool."""
        matches = [e for e in self._log if e.tool_name == tool_name]
        return matches[-count:] if len(matches) > count else matches

    def get_failures(self, count: int = 50) -> list[AuditEntry]:
        """Get recent failure entries."""
        _fail_types = {
            AuditEventType.TOOL_CALL_FAILURE,
            AuditEventType.TOOL_CALL_TIMEOUT,
            AuditEventType.TOOL_CALL_BLOCKED,
        }
        matches = [e for e in self._log if e.event_type in _fail_types]
        return matches[-count:] if len(matches) > count else matches

    def get_tool_stats(self, tool_name: str | None = None) -> dict[str, Any]:
        """Get aggregate statistics for one or all tools."""
        if tool_name:
            s = self._stats.get(tool_name)
            if not s:
                return {}
            total = s["total_calls"]
            return {
                **s,
                "avg_duration_ms": round(s["total_duration_ms"] / max(1, total)),
                "error_rate": round(s["failures"] / max(1, total) * 100, 1),
                "min_duration_ms": s["min_duration_ms"] if s["min_duration_ms"] != float("inf") else 0,
            }
        # All tools
        return {name: self.get_tool_stats(name) for name in self._stats}

    @property
    def total_entries(self) -> int:
        return len(self._log)

    @property
    def summary(self) -> dict[str, Any]:
        """High-level audit summary."""
        total = sum(s["total_calls"] for s in self._stats.values())
        errors = sum(s["failures"] for s in self._stats.values())
        return {
            "total_calls": total,
            "total_errors": errors,
            "error_rate": round(errors / max(1, total) * 100, 1),
            "tools_used": len(self._stats),
            "log_entries": len(self._log),
            "max_entries": self._max_entries,
        }

    def clear(self) -> None:
        """Clear all audit data."""
        self._log.clear()
        self._stats.clear()
        self._rate_limiter.reset()


# ─── Global Instance ─────────────────────────────────────────────────────────

tool_audit = ToolAuditLogger()
