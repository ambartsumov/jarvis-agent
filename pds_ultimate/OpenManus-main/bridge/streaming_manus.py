"""Streaming Manus — emits IPC events during Think-Act-Observe (minimal OpenManus patch)."""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Optional

from app.agent.manus import Manus
from app.schema import AgentState, Message
from bridge.activity_ru import tool_title
from bridge.answer import is_internal_monologue, pick_user_answer

EventSink = Callable[[str, dict[str, Any]], Awaitable[None] | None]


class StreamingManus(Manus):
    """Manus with real-time event sink for OpenClaw bridge."""

    max_steps: int = 15

    _req_id: str = ""
    _event_sink: Optional[EventSink] = None

    def bind_stream(self, req_id: str, sink: EventSink) -> None:
        self._req_id = req_id
        self._event_sink = sink

    def prepare_for_run(self) -> None:
        """Reset conversation state between bridge runs without tearing down MCP."""
        self.memory.clear()
        self.current_step = 0
        self.state = AgentState.IDLE
        self.tool_calls = []

    async def step(self) -> str:
        result = await super().step()
        # Direct text reply without tool calls = task done (avoids extra think loops).
        if self.state != AgentState.FINISHED and self.memory.messages:
            last = self.memory.messages[-1]
            if (
                last.role == "assistant"
                and last.content
                and not last.tool_calls
                and not is_internal_monologue(last.content)
            ):
                self.state = AgentState.FINISHED
        return result

    async def _emit(self, kind: str, **payload: Any) -> None:
        if not self._event_sink:
            return
        result = self._event_sink(kind, payload)
        if hasattr(result, "__await__"):
            await result

    async def run(self, request: Optional[str] = None) -> str:
        if request:
            self.update_memory("user", request)
        final_parts: list[str] = []
        async with self.state_context(AgentState.RUNNING):
            while self.current_step < self.max_steps and self.state != AgentState.FINISHED:
                self.current_step += 1
                await self._emit(
                    "step",
                    step=self.current_step,
                )
                await self._emit(
                    "status",
                    title="🤔 Думаю…",
                    step=self.current_step,
                )
                step_result = await self.step()
                if self.is_stuck():
                    self.handle_stuck_state()
                final_parts.append(f"Step {self.current_step}: {step_result}")
            if self.current_step >= self.max_steps:
                self.current_step = 0
                self.state = AgentState.IDLE
                final_parts.append(f"Terminated: Reached max steps ({self.max_steps})")
        from app.sandbox.client import SANDBOX_CLIENT

        await SANDBOX_CLIENT.cleanup()

        # Prefer last user-facing assistant reply (skip internal English planning).
        answer = pick_user_answer(self.memory.messages)
        if not answer:
            for msg in reversed(self.memory.messages):
                if msg.role == "assistant" and msg.content and not is_internal_monologue(msg.content):
                    answer = msg.content.strip()
                    break
        if not answer:
            answer = "\n".join(final_parts) if final_parts else "Готово."
        await self._emit("final", content=answer)
        return answer

    async def think(self) -> bool:
        ok = await super().think()
        content = ""
        if self.memory.messages:
            last = self.memory.messages[-1]
            if last.role == "assistant" and last.content:
                content = last.content
        if content:
            await self._emit("thought", content=content[:4000])
        if self.tool_calls:
            for tc in self.tool_calls:
                args_raw = tc.function.arguments or "{}"
                try:
                    args = json.loads(args_raw)
                except json.JSONDecodeError:
                    args = {"raw": args_raw}
                title = tool_title(tc.function.name)
                await self._emit(
                    "status",
                    title=title,
                    step=self.current_step,
                )
                await self._emit(
                    "tool_start",
                    name=tc.function.name,
                    args=args,
                )
        return ok

    async def act(self) -> str:
        result = await super().act()
        if self.tool_calls:
            tool_msgs = [
                m for m in self.memory.messages[-len(self.tool_calls) :]
                if m.role == "tool"
            ]
            for tc, msg in zip(self.tool_calls, tool_msgs):
                await self._emit(
                    "tool_end",
                    name=tc.function.name,
                    output=(msg.content or "")[:8000],
                )
        return result
