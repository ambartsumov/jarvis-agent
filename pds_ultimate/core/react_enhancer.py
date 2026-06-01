"""
PDS-Ultimate ReAct Loop Enhancer
==================================
Step 16: Smart observation truncation, action dedup, token budget,
         advanced oscillation detection, self-reflection.

PROBLEMS SOLVED:
1. Observation truncation: [:2000] → LLM-summary for long results
2. Action dedup: same tool + same params → skip with warning
3. Token budget: per-request budget tracking, stop when exceeded
4. Oscillation: ABAB, ABCABC, AABAB patterns detected
5. Self-reflection: after failed tool call → analyze what went wrong

ARCHITECTURE:
    Before each tool call:
        ActionDedup.check() → already tried? → skip
        TokenBudget.check() → budget exceeded? → force finish

    After each tool result:
        ObservationSummarizer.truncate() → smart truncation
        SelfReflector.reflect() → learn from failure (if failed)
        OscillationDetector.check() → stuck in loop? → break out
"""

from __future__ import annotations

import hashlib
import time
from collections import Counter
from dataclasses import dataclass, field

# ═══════════════════════════════════════════════════════════════════════════════
# OBSERVATION SUMMARIZER
# ═══════════════════════════════════════════════════════════════════════════════


class ObservationSummarizer:
    """
    Smart observation truncation.

    Instead of blind [:2000], applies intelligent truncation:
    - Short results (< threshold): pass through unchanged
    - Medium results: truncate with structure preservation
    - Large results: extract key parts + add summary header
    """

    def __init__(
        self,
        short_threshold: int = 1500,
        max_length: int = 2500,
    ):
        self.short_threshold = short_threshold
        self.max_length = max_length

    def truncate(self, text: str, tool_name: str = "") -> str:
        """
        Intelligently truncate observation text.

        Preserves:
        - First section (usually most relevant)
        - Last section (usually conclusion/summary)
        - Key data (numbers, lists)
        """
        if not text:
            return ""

        if len(text) <= self.short_threshold:
            return text

        # For structured data (JSON-like), preserve structure
        stripped = text.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            return self._truncate_structured(text)

        # For plain text: head + tail strategy
        return self._truncate_text(text, tool_name)

    def _truncate_structured(self, text: str) -> str:
        """Truncate JSON/structured data preserving opening."""
        if len(text) <= self.max_length:
            return text

        # Keep first 70%, last 20% of budget
        head_budget = int(self.max_length * 0.7)
        tail_budget = int(self.max_length * 0.2)

        head = text[:head_budget]
        tail = text[-tail_budget:]

        omitted = len(text) - head_budget - tail_budget
        return f"{head}\n\n... [{omitted} символов пропущено] ...\n\n{tail}"

    def _truncate_text(self, text: str, tool_name: str) -> str:
        """Truncate plain text with head+tail strategy."""
        if len(text) <= self.max_length:
            return text

        lines = text.split("\n")
        total_lines = len(lines)

        # Single-line text — just hard truncate
        if total_lines <= 1:
            return text[:self.max_length] + f"\n... [обрезано, всего {len(text)} символов]"

        # Head: first 60% of budget in lines
        head_lines = max(3, int(total_lines * 0.6))
        # Tail: last 20%
        tail_lines = max(2, int(total_lines * 0.2))

        if head_lines + tail_lines >= total_lines:
            # Just hard truncate
            return text[:self.max_length] + f"\n... [обрезано, всего {len(text)} символов]"

        head = "\n".join(lines[:head_lines])
        tail = "\n".join(lines[-tail_lines:])

        # If still too long, hard-cap each section
        head_budget = int(self.max_length * 0.65)
        tail_budget = int(self.max_length * 0.25)

        if len(head) > head_budget:
            head = head[:head_budget] + "..."
        if len(tail) > tail_budget:
            tail = "..." + tail[-tail_budget:]

        omitted = total_lines - head_lines - tail_lines
        header = f"[Результат {tool_name}: {len(text)} символов, {total_lines} строк]"
        return f"{header}\n{head}\n\n... [{omitted} строк пропущено] ...\n\n{tail}"


# ═══════════════════════════════════════════════════════════════════════════════
# ACTION DEDUP
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class ActionRecord:
    """Record of a tool call."""
    tool_name: str
    params_hash: str
    timestamp: float
    success: bool
    result_preview: str = ""


class ActionDedup:
    """
    Detect and prevent duplicate tool calls.

    Tracks (tool_name, params_hash) pairs.
    Same tool + same params within window → skip.
    """

    def __init__(self, window_size: int = 20):
        self.window_size = window_size
        self._history: list[ActionRecord] = []

    def _hash_params(self, params: dict | None) -> str:
        """Create stable hash of parameters."""
        if not params:
            return "empty"
        # Sort keys for stable hashing
        try:
            import json
            canonical = json.dumps(params, sort_keys=True, ensure_ascii=False)
            return hashlib.md5(canonical.encode()).hexdigest()[:12]
        except (TypeError, ValueError):
            return hashlib.md5(str(params).encode()).hexdigest()[:12]

    def check(self, tool_name: str, params: dict | None = None) -> tuple[bool, str]:
        """
        Check if this action is a duplicate.

        Returns: (is_duplicate, reason)
        """
        params_hash = self._hash_params(params)

        # Look in recent history
        for record in reversed(self._history[-self.window_size:]):
            if record.tool_name == tool_name and record.params_hash == params_hash:
                return True, (
                    f"Duplicate: {tool_name} с теми же параметрами уже вызывался. "
                    f"Предыдущий результат: {record.result_preview[:200]}"
                )

        return False, ""

    def record(
        self,
        tool_name: str,
        params: dict | None,
        success: bool,
        result: str = "",
    ) -> None:
        """Record a tool call."""
        self._history.append(ActionRecord(
            tool_name=tool_name,
            params_hash=self._hash_params(params),
            timestamp=time.time(),
            success=success,
            result_preview=result[:300],
        ))

        # Bound history to window_size
        if len(self._history) > self.window_size:
            self._history = self._history[-self.window_size:]

    def get_history(self) -> list[ActionRecord]:
        """Return action history."""
        return list(self._history)

    def clear(self) -> None:
        """Clear action history."""
        self._history.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# TOKEN BUDGET
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class BudgetSnapshot:
    """Snapshot of token budget state."""
    total_budget: int
    tokens_used: int
    tokens_remaining: int
    percentage_used: float
    is_exceeded: bool
    breakdown: dict[str, int] = field(default_factory=dict)


class TokenBudget:
    """
    Per-request token budget tracking.

    Tracks token usage across:
    - Input prompts
    - Tool call results (observations)
    - LLM responses
    - Planning overhead
    """

    # Default budget: ~100k tokens per request (DeepSeek context window safe)
    DEFAULT_BUDGET = 100_000
    # Warning threshold: 80% of budget
    WARNING_THRESHOLD = 0.8

    def __init__(self, budget: int | None = None):
        self.total_budget = budget or self.DEFAULT_BUDGET
        self._usage: dict[str, int] = {
            "input": 0,
            "output": 0,
            "tool_results": 0,
            "planning": 0,
            "reflection": 0,
        }

    @property
    def tokens_used(self) -> int:
        return sum(self._usage.values())

    @property
    def tokens_remaining(self) -> int:
        return max(0, self.total_budget - self.tokens_used)

    @property
    def is_exceeded(self) -> bool:
        return self.tokens_used >= self.total_budget

    @property
    def is_warning(self) -> bool:
        return (
            self.tokens_used >= self.total_budget * self.WARNING_THRESHOLD
            and not self.is_exceeded
        )

    def add(self, category: str, tokens: int) -> None:
        """Add token usage for a category."""
        if category not in self._usage:
            self._usage[category] = 0
        self._usage[category] += tokens

    def check(self) -> BudgetSnapshot:
        """Check current budget state."""
        used = self.tokens_used
        return BudgetSnapshot(
            total_budget=self.total_budget,
            tokens_used=used,
            tokens_remaining=max(0, self.total_budget - used),
            percentage_used=round(used / max(1, self.total_budget), 3),
            is_exceeded=self.is_exceeded,
            breakdown=dict(self._usage),
        )

    def reset(self) -> None:
        """Reset all usage counters."""
        for key in self._usage:
            self._usage[key] = 0


# ═══════════════════════════════════════════════════════════════════════════════
# OSCILLATION DETECTOR (ADVANCED)
# ═══════════════════════════════════════════════════════════════════════════════


class OscillationDetector:
    """
    Advanced oscillation detection.

    Detects patterns beyond simple ABAB:
    - ABAB (2-cycle)
    - ABCABC (3-cycle)
    - AABAB (with stuttering)
    - Any repeating cycle up to length max_cycle_length
    """

    def __init__(
        self,
        min_window: int = 4,
        max_cycle_length: int = 4,
        min_repeats: int = 2,
    ):
        self.min_window = min_window
        self.max_cycle_length = max_cycle_length
        self.min_repeats = min_repeats
        self._actions: list[str] = []

    def record(self, action_key: str) -> None:
        """Record an action for oscillation tracking."""
        self._actions.append(action_key)

    def check(self) -> tuple[bool, str]:
        """
        Check for oscillation patterns.

        Returns: (is_oscillating, pattern_description)
        """
        # Check for same action repeated 3x (earliest check)
        if len(self._actions) >= 3:
            recent = self._actions[-3:]
            if len(set(recent)) == 1:
                return True, f"Same action repeated 3x: {recent[0]}"

        if len(self._actions) < self.min_window:
            return False, ""

        # Try cycle lengths from 1 to max_cycle_length
        for cycle_len in range(1, self.max_cycle_length + 1):
            if self._check_cycle(cycle_len):
                pattern = " → ".join(self._actions[-cycle_len:])
                return True, f"Oscillation detected: {pattern} (cycle={cycle_len})"

        return False, ""

    def _check_cycle(self, cycle_len: int) -> bool:
        """Check if the last N actions form a repeating cycle."""
        needed = cycle_len * self.min_repeats
        if len(self._actions) < needed:
            return False

        recent = self._actions[-needed:]
        cycle = recent[-cycle_len:]

        for i in range(self.min_repeats):
            start = i * cycle_len
            segment = recent[start:start + cycle_len]
            if segment != cycle:
                return False

        return True

    def clear(self) -> None:
        """Reset oscillation tracker."""
        self._actions.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# SELF-REFLECTOR
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class ReflectionResult:
    """Result of self-reflection."""
    should_retry: bool
    reason: str
    suggestion: str
    failure_type: str = ""


class SelfReflector:
    """
    Self-reflection after failed tool calls.

    Analyzes what went wrong and suggests corrective action.
    Pure heuristic — no LLM cost for reflection.
    """

    _ERROR_STRATEGIES: dict[str, tuple[str, str]] = {
        "not found": ("resource_missing", "Попробуй другой запрос или инструмент"),
        "не найден": ("resource_missing", "Попробуй изменить параметры поиска"),
        "timeout": ("timeout", "Попробуй с меньшим объёмом данных"),
        "timed out": ("timeout", "Уменьши scope запроса"),
        "rate limit": ("rate_limit", "Подожди и попробуй снова"),
        "429": ("rate_limit", "API rate limited — подожди"),
        "permission": ("permission", "Нет доступа — попробуй другой подход"),
        "403": ("permission", "Доступ запрещён — используй альтернативный источник"),
        "invalid": ("validation", "Проверь параметры — формат неверный"),
        "parse": ("parse_error", "Формат данных неожиданный — попробуй другой инструмент"),
        "connection": ("network", "Проблемы с сетью — попробуй позже"),
        "network": ("network", "Сетевая ошибка — попробуй альтернативный endpoint"),
    }

    def __init__(self, max_retries_per_type: int = 2):
        self.max_retries_per_type = max_retries_per_type
        self._failure_counts: Counter = Counter()

    def reflect(
        self,
        tool_name: str,
        error_message: str,
        attempt: int = 1,
    ) -> ReflectionResult:
        """
        Analyze a tool failure and suggest next action.

        Returns ReflectionResult with retry recommendation.
        """
        error_lower = error_message.lower()

        # Find matching strategy
        failure_type = "unknown"
        suggestion = "Попробуй альтернативный подход"

        for keyword, (ftype, sug) in self._ERROR_STRATEGIES.items():
            if keyword in error_lower:
                failure_type = ftype
                suggestion = sug
                break

        # Track failure count for this type
        key = f"{tool_name}:{failure_type}"
        self._failure_counts[key] += 1
        count = self._failure_counts[key]

        # Decide on retry
        should_retry = count <= self.max_retries_per_type
        reason = (
            f"Ошибка {tool_name}: {failure_type} "
            f"(попытка {count}/{self.max_retries_per_type})"
        )

        if not should_retry:
            suggestion = (
                f"Исчерпаны попытки для {tool_name} ({failure_type}). "
                f"Используй другой инструмент или ответь без него."
            )

        return ReflectionResult(
            should_retry=should_retry,
            reason=reason,
            suggestion=suggestion,
            failure_type=failure_type,
        )

    def get_failure_summary(self) -> dict[str, int]:
        """Return failure counts by type."""
        return dict(self._failure_counts)

    def clear(self) -> None:
        """Reset failure tracking."""
        self._failure_counts.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# REACT ENHANCER (Unified API)
# ═══════════════════════════════════════════════════════════════════════════════


class ReactEnhancer:
    """
    Unified ReAct loop enhancement.

    Combines all improvements into a single API:
    - check_action() — dedup + budget check before tool call
    - process_observation() — smart truncation after tool result
    - reflect_on_failure() — self-reflection after error
    - check_oscillation() — advanced oscillation detection
    """

    def __init__(
        self,
        token_budget: int | None = None,
        max_observation_length: int = 2500,
        dedup_window: int = 20,
    ):
        self.summarizer = ObservationSummarizer(
            max_length=max_observation_length,
        )
        self.dedup = ActionDedup(window_size=dedup_window)
        self.budget = TokenBudget(budget=token_budget)
        self.oscillation = OscillationDetector()
        self.reflector = SelfReflector()

    def check_action(
        self,
        tool_name: str,
        params: dict | None = None,
    ) -> tuple[bool, str]:
        """
        Pre-flight check before executing a tool call.

        Returns: (should_execute, reason_if_not)
        """
        # Budget check
        if self.budget.is_exceeded:
            return False, (
                f"Token budget exceeded "
                f"({self.budget.tokens_used}/{self.budget.total_budget}). "
                f"Заверши задачу с имеющимися данными."
            )

        # Dedup check
        is_dup, reason = self.dedup.check(tool_name, params)
        if is_dup:
            return False, reason

        # Oscillation check
        action_key = f"{tool_name}:{self.dedup._hash_params(params)}"
        self.oscillation.record(action_key)
        is_osc, osc_reason = self.oscillation.check()
        if is_osc:
            return False, f"Обнаружена осцилляция: {osc_reason}. Заверши задачу."

        return True, ""

    def process_observation(
        self,
        observation: str,
        tool_name: str = "",
        success: bool = True,
        params: dict | None = None,
    ) -> str:
        """
        Process a tool observation (result).

        1. Smart truncation
        2. Record action
        3. Track token usage
        """
        # Truncate intelligently
        truncated = self.summarizer.truncate(observation, tool_name)

        # Record for dedup
        self.dedup.record(tool_name, params, success, truncated)

        # Track tokens (rough estimate: 1 token ≈ 4 chars for Russian)
        self.budget.add("tool_results", len(truncated) // 3)

        return truncated

    def reflect_on_failure(
        self,
        tool_name: str,
        error_message: str,
        attempt: int = 1,
    ) -> ReflectionResult:
        """Analyze failure and suggest next action."""
        return self.reflector.reflect(tool_name, error_message, attempt)

    def add_token_usage(self, category: str, tokens: int) -> None:
        """Track token usage for budget."""
        self.budget.add(category, tokens)

    def get_budget(self) -> BudgetSnapshot:
        """Get current budget state."""
        return self.budget.check()

    def reset(self) -> None:
        """Reset all state for new request."""
        self.dedup.clear()
        self.budget.reset()
        self.oscillation.clear()
        self.reflector.clear()
