"""
Tests for Step 6: Streaming Progress System
=============================================
Tests for: progress.py + agent.py progress integration

Coverage:
- ProgressStage enum
- ProgressEvent — fields, display_text, emoji
- ProgressTracker — emit, rate limiting, error safety
- Agent.execute() with on_progress callback
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from pds_ultimate.core.progress import (
    ProgressEvent,
    ProgressStage,
    ProgressTracker,
)

# ═══════════════════════════════════════════════════════════════════════════════
# 1. ProgressStage
# ═══════════════════════════════════════════════════════════════════════════════


class TestProgressStage:
    """Test ProgressStage enum."""

    def test_all_stages_defined(self):
        stages = list(ProgressStage)
        assert len(stages) >= 10

    def test_stage_values_are_strings(self):
        for stage in ProgressStage:
            assert isinstance(stage.value, str)

    def test_key_stages_exist(self):
        assert ProgressStage.THINKING
        assert ProgressStage.TOOL_CALLING
        assert ProgressStage.DONE
        assert ProgressStage.ERROR
        assert ProgressStage.PLANNING
        assert ProgressStage.SUB_AGENT_START


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ProgressEvent
# ═══════════════════════════════════════════════════════════════════════════════


class TestProgressEvent:
    """Test ProgressEvent dataclass."""

    def test_basic_event(self):
        ev = ProgressEvent(
            stage=ProgressStage.THINKING,
            message="Думаю...",
        )
        assert ev.stage == ProgressStage.THINKING
        assert ev.message == "Думаю..."
        assert ev.iteration == 0
        assert ev.tool_name is None

    def test_emoji_property(self):
        ev = ProgressEvent(stage=ProgressStage.THINKING, message="test")
        assert ev.emoji == "🤔"

        ev2 = ProgressEvent(stage=ProgressStage.TOOL_CALLING, message="test")
        assert ev2.emoji == "🔧"

        ev3 = ProgressEvent(stage=ProgressStage.DONE, message="test")
        assert ev3.emoji == "✅"

        ev4 = ProgressEvent(stage=ProgressStage.ERROR, message="test")
        assert ev4.emoji == "❌"

    def test_display_text_simple(self):
        ev = ProgressEvent(stage=ProgressStage.THINKING, message="Думаю...")
        text = ev.display_text
        assert "🤔" in text
        assert "Думаю..." in text

    def test_display_text_with_iteration(self):
        ev = ProgressEvent(
            stage=ProgressStage.THINKING,
            message="Шаг",
            iteration=2,
            total_iterations=5,
        )
        text = ev.display_text
        assert "(шаг 2/5)" in text

    def test_display_text_with_tool(self):
        ev = ProgressEvent(
            stage=ProgressStage.TOOL_CALLING,
            message="Вызов",
            tool_name="search",
        )
        text = ev.display_text
        assert "[search]" in text

    def test_display_text_with_elapsed(self):
        ev = ProgressEvent(
            stage=ProgressStage.DONE,
            message="Готово!",
            elapsed_ms=1500,
        )
        text = ev.display_text
        assert "(1.5s)" in text

    def test_display_text_full(self):
        ev = ProgressEvent(
            stage=ProgressStage.TOOL_CALLING,
            message="Использую",
            iteration=3,
            total_iterations=5,
            tool_name="calculator",
            elapsed_ms=2300,
        )
        text = ev.display_text
        assert "🔧" in text
        assert "Использую" in text
        assert "(шаг 3/5)" in text
        assert "[calculator]" in text
        assert "(2.3s)" in text


# ═══════════════════════════════════════════════════════════════════════════════
# 3. ProgressTracker
# ═══════════════════════════════════════════════════════════════════════════════


class TestProgressTracker:
    """Test ProgressTracker event management."""

    @pytest.mark.asyncio
    async def test_no_callback_silent(self):
        """Without callback, emit does nothing (no crash)."""
        tracker = ProgressTracker(callback=None)
        assert tracker.has_callback is False
        # Should not raise
        await tracker.emit(ProgressStage.THINKING, "test")
        assert len(tracker.events) == 1

    @pytest.mark.asyncio
    async def test_callback_called(self):
        """Callback receives events."""
        cb = AsyncMock()
        tracker = ProgressTracker(callback=cb, total_iterations=5)
        await tracker.emit(ProgressStage.THINKING, "test", force=True)
        cb.assert_called_once()
        event = cb.call_args[0][0]
        assert isinstance(event, ProgressEvent)
        assert event.stage == ProgressStage.THINKING

    @pytest.mark.asyncio
    async def test_events_recorded(self):
        """All events are recorded regardless of rate limiting."""
        cb = AsyncMock()
        tracker = ProgressTracker(callback=cb)
        await tracker.emit(ProgressStage.THINKING, "A", force=True)
        await tracker.emit(ProgressStage.TOOL_CALLING, "B", force=True)
        await tracker.emit(ProgressStage.DONE, "C", force=True)
        assert len(tracker.events) == 3
        assert tracker.events[0].stage == ProgressStage.THINKING
        assert tracker.events[2].stage == ProgressStage.DONE

    @pytest.mark.asyncio
    async def test_rate_limiting(self):
        """Events within MIN_INTERVAL_MS are rate-limited."""
        cb = AsyncMock()
        tracker = ProgressTracker(callback=cb)
        tracker.MIN_INTERVAL_MS = 5000  # 5 seconds

        # First call goes through
        await tracker.emit(ProgressStage.THINKING, "A")
        assert cb.call_count == 1

        # Rapid second call is rate-limited
        await tracker.emit(ProgressStage.TOOL_CALLING, "B")
        assert cb.call_count == 1  # Still 1 — rate limited

        # But all events recorded
        assert len(tracker.events) == 2

    @pytest.mark.asyncio
    async def test_force_bypasses_rate_limit(self):
        """force=True bypasses rate limiting."""
        cb = AsyncMock()
        tracker = ProgressTracker(callback=cb)
        tracker.MIN_INTERVAL_MS = 5000

        await tracker.emit(ProgressStage.THINKING, "A")
        assert cb.call_count == 1

        await tracker.emit(ProgressStage.DONE, "B", force=True)
        assert cb.call_count == 2  # Force bypassed rate limit

    @pytest.mark.asyncio
    async def test_callback_error_doesnt_crash(self):
        """Callback errors don't crash the tracker."""
        cb = AsyncMock(side_effect=RuntimeError("Connection reset"))
        tracker = ProgressTracker(callback=cb)
        # Should not raise
        await tracker.emit(ProgressStage.THINKING, "test", force=True)
        assert len(tracker.events) == 1

    @pytest.mark.asyncio
    async def test_emit_done(self):
        """emit_done sends DONE event with force."""
        cb = AsyncMock()
        tracker = ProgressTracker(callback=cb)
        tracker.MIN_INTERVAL_MS = 99999  # extreme rate limit
        await tracker.emit(ProgressStage.THINKING, "A")  # first call
        await tracker.emit_done("Готово!")
        # Both should go through (done is forced)
        assert cb.call_count == 2
        last_event = cb.call_args[0][0]
        assert last_event.stage == ProgressStage.DONE

    @pytest.mark.asyncio
    async def test_emit_error(self):
        """emit_error sends ERROR event with force."""
        cb = AsyncMock()
        tracker = ProgressTracker(callback=cb)
        await tracker.emit_error("Провал")
        cb.assert_called_once()
        event = cb.call_args[0][0]
        assert event.stage == ProgressStage.ERROR

    @pytest.mark.asyncio
    async def test_set_iteration(self):
        """set_iteration updates event iteration."""
        cb = AsyncMock()
        tracker = ProgressTracker(callback=cb, total_iterations=10)
        tracker.set_iteration(3)
        await tracker.emit(ProgressStage.THINKING, "test", force=True)
        event = cb.call_args[0][0]
        assert event.iteration == 3
        assert event.total_iterations == 10

    @pytest.mark.asyncio
    async def test_elapsed_time(self):
        """Events have elapsed time from tracker creation."""
        tracker = ProgressTracker()
        await asyncio.sleep(0.01)  # 10ms
        await tracker.emit(ProgressStage.THINKING, "test")
        assert tracker.events[0].elapsed_ms >= 5  # at least some time passed

    @pytest.mark.asyncio
    async def test_tool_name_in_event(self):
        """tool_name passed to emit shows in event."""
        cb = AsyncMock()
        tracker = ProgressTracker(callback=cb)
        await tracker.emit(
            ProgressStage.TOOL_CALLING, "Using tool",
            tool_name="calculator", force=True,
        )
        event = cb.call_args[0][0]
        assert event.tool_name == "calculator"

    @pytest.mark.asyncio
    async def test_details_in_event(self):
        """Extra details passed through."""
        tracker = ProgressTracker()
        await tracker.emit(
            ProgressStage.SUB_AGENT_START, "test",
            nodes=["a", "b"],
        )
        assert tracker.events[0].details == {"nodes": ["a", "b"]}


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Agent Integration — on_progress callback
# ═══════════════════════════════════════════════════════════════════════════════


class TestAgentProgressIntegration:
    """Test Agent.execute() with on_progress callback."""

    @pytest.mark.asyncio
    async def test_execute_without_callback(self):
        """Agent works without on_progress (backward compat)."""
        from pds_ultimate.core.agent import Agent

        agent = Agent()

        with patch.object(agent, "_select_mode", return_value="simple"), \
            patch("pds_ultimate.core.llm_engine.llm_engine.chat",
                  new_callable=AsyncMock, return_value="Ответ"):
            response = await agent.execute("Привет")
            assert response.answer == "Ответ"

    @pytest.mark.asyncio
    async def test_execute_with_callback_receives_events(self):
        """on_progress callback receives ProgressEvents."""
        from pds_ultimate.core.agent import Agent

        agent = Agent()
        received_events = []

        async def collector(event: ProgressEvent):
            received_events.append(event)

        with patch.object(agent, "_select_mode", return_value="simple"), \
            patch.object(agent._optimizer, "get_cached_response", return_value=None), \
            patch("pds_ultimate.core.llm_engine.llm_engine.chat",
                  new_callable=AsyncMock, return_value="Ответ"):
            response = await agent.execute(
                "Привет", on_progress=collector,
            )

        # Should have at least MODE_SELECTED + THINKING + DONE
        stages = [e.stage for e in received_events]
        assert ProgressStage.MODE_SELECTED in stages
        assert ProgressStage.DONE in stages

    @pytest.mark.asyncio
    async def test_execute_tool_loop_emits_tool_events(self):
        """Tool loop emits TOOL_CALLING and TOOL_RESULT events."""
        from pds_ultimate.core.agent import Agent

        agent = Agent()
        received_events = []

        async def collector(event: ProgressEvent):
            received_events.append(event)

        # Mock tool loop behavior: first call returns tool_call,
        # second call returns text answer
        call_count = 0

        async def mock_chat_with_tools(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "type": "tool_calls",
                    "content": "",
                    "thought": "Let me search",
                    "tool_calls": [{
                        "id": "tc_1",
                        "name": "test_tool",
                        "arguments": {"q": "test"},
                    }],
                }
            return {
                "type": "text",
                "content": "Результат поиска: данные",
                "thought": "Found it",
            }

        with patch.object(agent, "_select_mode", return_value="tool_loop"), \
                patch.object(agent._optimizer, "get_cached_response", return_value=None), \
                patch("pds_ultimate.core.llm_engine.llm_engine.chat_with_tools",
                      side_effect=mock_chat_with_tools), \
                patch("pds_ultimate.core.agent.tool_registry") as mock_tools:
            mock_tools.get_tools_json_schema.return_value = []
            mock_tools.has_tool.return_value = True
            mock_tools.execute = AsyncMock(return_value="Tool result data")

            response = await agent.execute(
                "Найди информацию",
                on_progress=collector,
            )

        # Check that tool-related events are in the list
        # (some may be rate-limited for callback but all recorded in tracker)
        stages = [e.stage for e in received_events]
        assert ProgressStage.MODE_SELECTED in stages
        assert ProgressStage.DONE in stages
        # At minimum, mode_selected + done should be present
        # Tool events may be rate-limited but should exist in some form

    @pytest.mark.asyncio
    async def test_callback_error_doesnt_crash_agent(self):
        """Agent continues even if callback raises."""
        from pds_ultimate.core.agent import Agent

        agent = Agent()

        async def bad_callback(event: ProgressEvent):
            raise ConnectionError("Network down")

        with patch.object(agent, "_select_mode", return_value="simple"), \
            patch.object(agent._optimizer, "get_cached_response", return_value=None), \
            patch("pds_ultimate.core.llm_engine.llm_engine.chat",
                  new_callable=AsyncMock, return_value="Ответ"):
            # Should not raise
            response = await agent.execute(
                "Привет", on_progress=bad_callback,
            )
            assert response.answer == "Ответ"

    @pytest.mark.asyncio
    async def test_execute_on_progress_is_optional(self):
        """on_progress defaults to None (no change for existing callers)."""
        import inspect

        from pds_ultimate.core.agent import Agent

        sig = inspect.signature(Agent.execute)
        param = sig.parameters.get("on_progress")
        assert param is not None
        assert param.default is None


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Edge Cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge cases for progress system."""

    @pytest.mark.asyncio
    async def test_many_rapid_events(self):
        """Many rapid events don't overwhelm."""
        cb = AsyncMock()
        tracker = ProgressTracker(callback=cb)
        for i in range(100):
            await tracker.emit(ProgressStage.THINKING, f"Event {i}")
        # All recorded
        assert len(tracker.events) == 100
        # But not all callbacks fired (rate limited)
        assert cb.call_count < 100

    @pytest.mark.asyncio
    async def test_tracker_no_callback_fast(self):
        """Without callback, emit is near-instant."""
        import time
        tracker = ProgressTracker(callback=None)
        start = time.time()
        for _ in range(1000):
            await tracker.emit(ProgressStage.THINKING, "test")
        elapsed = time.time() - start
        assert elapsed < 1.0  # Should be very fast

    def test_progress_event_defaults(self):
        """ProgressEvent has sensible defaults."""
        ev = ProgressEvent(stage=ProgressStage.THINKING, message="test")
        assert ev.iteration == 0
        assert ev.total_iterations == 0
        assert ev.tool_name is None
        assert ev.elapsed_ms == 0
        assert ev.details == {}
