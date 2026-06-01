"""
PDS-Ultimate — Streaming Progress System
==========================================
Real-time progress events for Agent execution.

Eliminates 30-60s wait without feedback.
Provides typed events at each stage of execution:
- Mode selection
- Thinking / Planning
- Tool execution
- Sub-agent delegation
- Verification
- Final answer

Usage:
    async def my_handler(event: ProgressEvent):
        await bot.edit_message(msg_id, event.display_text)

    response = await agent.execute(
        "Создай отчёт", chat_id=123,
        on_progress=my_handler,
    )
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger("pds_ultimate")

# ═══════════════════════════════════════════════════════════════════════════════
# 1. Progress Event Types
# ═══════════════════════════════════════════════════════════════════════════════


class ProgressStage(str, Enum):
    """Stages of agent execution."""
    MODE_SELECTED = "mode_selected"
    CACHE_HIT = "cache_hit"
    THINKING = "thinking"
    PLANNING = "planning"
    TOOL_CALLING = "tool_calling"
    TOOL_RESULT = "tool_result"
    SUB_AGENT_START = "sub_agent_start"
    SUB_AGENT_DONE = "sub_agent_done"
    REFLECTING = "reflecting"
    VERIFYING = "verifying"
    REPLANNING = "replanning"
    FINALIZING = "finalizing"
    DONE = "done"
    ERROR = "error"


# Stage → emoji mapping for Telegram display
_STAGE_EMOJI: dict[ProgressStage, str] = {
    ProgressStage.MODE_SELECTED: "🎯",
    ProgressStage.CACHE_HIT: "⚡",
    ProgressStage.THINKING: "🤔",
    ProgressStage.PLANNING: "📋",
    ProgressStage.TOOL_CALLING: "🔧",
    ProgressStage.TOOL_RESULT: "📊",
    ProgressStage.SUB_AGENT_START: "👥",
    ProgressStage.SUB_AGENT_DONE: "✅",
    ProgressStage.REFLECTING: "💭",
    ProgressStage.VERIFYING: "🔍",
    ProgressStage.REPLANNING: "🔄",
    ProgressStage.FINALIZING: "📝",
    ProgressStage.DONE: "✅",
    ProgressStage.ERROR: "❌",
}


@dataclass
class ProgressEvent:
    """
    A single progress event from Agent execution.

    Designed for real-time display in Telegram via edit_message.
    """
    stage: ProgressStage
    message: str
    iteration: int = 0
    total_iterations: int = 0
    tool_name: Optional[str] = None
    elapsed_ms: int = 0
    details: dict = field(default_factory=dict)

    @property
    def emoji(self) -> str:
        return _STAGE_EMOJI.get(self.stage, "⏳")

    @property
    def display_text(self) -> str:
        """Format for Telegram display."""
        parts = [f"{self.emoji} {self.message}"]

        if self.iteration > 0:
            parts.append(f"(шаг {self.iteration}/{self.total_iterations})")

        if self.tool_name:
            parts.append(f"[{self.tool_name}]")

        if self.elapsed_ms > 0:
            secs = self.elapsed_ms / 1000
            parts.append(f"({secs:.1f}s)")

        return " ".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Callback Type
# ═══════════════════════════════════════════════════════════════════════════════

# Callback signature: async function that receives ProgressEvent
ProgressCallback = Callable[[ProgressEvent], Coroutine[Any, Any, None]]


# ═══════════════════════════════════════════════════════════════════════════════
# 3. ProgressTracker — manages event emission
# ═══════════════════════════════════════════════════════════════════════════════


class ProgressTracker:
    """
    Tracks execution progress and emits events.

    Features:
    - Rate limiting: at most 1 event per MIN_INTERVAL_MS
    - Batching: groups rapid events, emits last
    - Error-safe: callback failures don't crash agent
    - Optional: if no callback set, events are silently dropped
    """

    MIN_INTERVAL_MS = 800  # min ms between events (avoid Telegram rate limit)

    def __init__(
        self,
        callback: Optional[ProgressCallback] = None,
        total_iterations: int = 5,
    ):
        self._callback = callback
        self._total_iterations = total_iterations
        self._start_time = time.time()
        self._last_emit_time = 0.0
        self._events: list[ProgressEvent] = []
        self._current_iteration = 0

    @property
    def has_callback(self) -> bool:
        return self._callback is not None

    @property
    def events(self) -> list[ProgressEvent]:
        """All events emitted so far."""
        return list(self._events)

    def set_iteration(self, n: int) -> None:
        """Update current iteration counter."""
        self._current_iteration = n

    async def emit(
        self,
        stage: ProgressStage,
        message: str,
        tool_name: Optional[str] = None,
        force: bool = False,
        **details,
    ) -> None:
        """
        Emit a progress event.

        Args:
            stage: Event stage
            message: Human-readable message
            tool_name: Optional tool being used
            force: Bypass rate limiting (for DONE/ERROR)
            **details: Extra metadata
        """
        now = time.time()
        elapsed_ms = int((now - self._start_time) * 1000)

        event = ProgressEvent(
            stage=stage,
            message=message,
            iteration=self._current_iteration,
            total_iterations=self._total_iterations,
            tool_name=tool_name,
            elapsed_ms=elapsed_ms,
            details=details,
        )

        self._events.append(event)

        # Rate limit (skip if too soon, unless forced)
        if not force:
            since_last = (now - self._last_emit_time) * 1000
            if since_last < self.MIN_INTERVAL_MS:
                return

        # Fire callback
        if self._callback:
            try:
                await self._callback(event)
                self._last_emit_time = now
            except Exception as e:
                logger.warning(f"Progress callback error: {e}")

    async def emit_done(self, message: str = "Готово!") -> None:
        """Emit final DONE event (always sent)."""
        await self.emit(ProgressStage.DONE, message, force=True)

    async def emit_error(self, message: str = "Ошибка") -> None:
        """Emit ERROR event (always sent)."""
        await self.emit(ProgressStage.ERROR, message, force=True)
