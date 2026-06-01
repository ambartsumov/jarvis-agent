"""WebSocket client to OpenManus bridge — used by PDS Telegram bot and OpenClaw relay."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any, Awaitable, Callable

from websockets.asyncio.client import connect

from pds_ultimate.config import logger
from pds_ultimate.core.agent.types import AgentResponse, AgentStep

StepCallback = Callable[[str], Awaitable[None]] | None

DEFAULT_WS_URL = os.environ.get(
    "MANUS_BRIDGE_WS",
    "ws://127.0.0.1:8765/manus",
)


class ManusBridgeClient:
    """Async IPC client — streams Manus events over WebSocket (no CLI)."""

    def __init__(self, url: str = DEFAULT_WS_URL) -> None:
        self.url = url
        self._ws: Any = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        if self._ws is not None:
            return
        self._ws = await connect(
            self.url,
            open_timeout=10,
            close_timeout=5,
            ping_interval=60,
            ping_timeout=300,
        )
        logger.info(f"Manus bridge connected: {self.url}")

    async def close(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def run(
        self,
        message: str,
        *,
        session_id: str | int,
        context: dict[str, Any] | None = None,
        step_callback: StepCallback = None,
        timeout: float = 600.0,
    ) -> AgentResponse:
        req_id = str(uuid.uuid4())
        steps: list[AgentStep] = []
        tools_used: list[str] = []
        final_answer = ""
        iteration = 0

        async with self._lock:
            await self.connect()
            assert self._ws is not None

            payload = {
                "type": "run",
                "id": req_id,
                "session_id": str(session_id),
                "message": message,
                "context": context or {},
            }
            await self._ws.send(json.dumps(payload, ensure_ascii=False))

            try:
                async with asyncio.timeout(timeout):
                    while True:
                        raw = await self._ws.recv()
                        msg = json.loads(raw)
                        if msg.get("id") not in (req_id, "", None) and msg.get("type") != "pong":
                            continue

                        mtype = msg.get("type")
                        if mtype == "event":
                            ev = msg.get("event", "")
                            if ev == "step":
                                iteration = int(msg.get("step") or iteration)
                            elif ev == "thought":
                                content = msg.get("content") or ""
                                if step_callback and content:
                                    preview = content[:120].replace("\n", " ")
                                    await step_callback(f"💭 {preview}")
                            elif ev == "tool_start":
                                name = msg.get("name") or "tool"
                                tools_used.append(name)
                                if step_callback:
                                    await step_callback(f"🔧 {name}")
                            elif ev == "tool_end":
                                name = msg.get("name") or "tool"
                                obs = (msg.get("output") or "")[:4000]
                                steps.append(
                                    AgentStep(
                                        iteration=iteration or len(steps) + 1,
                                        action="tool_call",
                                        tool_name=name,
                                        observation=obs,
                                    )
                                )
                            elif ev == "final":
                                final_answer = msg.get("content") or final_answer
                            elif ev == "error":
                                err = msg.get("message") or "Unknown error"
                                return AgentResponse(
                                    answer=f"❌ {err}",
                                    steps=steps,
                                    tools_used=list(dict.fromkeys(tools_used)),
                                    verified=False,
                                    total_iterations=iteration,
                                )
                        elif mtype == "error":
                            return AgentResponse(
                                answer=f"❌ {msg.get('message', 'bridge error')}",
                                verified=False,
                            )
                        elif mtype == "done":
                            break
            except TimeoutError:
                await self._cancel(req_id)
                return AgentResponse(
                    answer="⏱ Превышен лимит времени (Manus bridge).",
                    steps=steps,
                    tools_used=list(dict.fromkeys(tools_used)),
                    verified=False,
                )

        if not final_answer:
            final_answer = ""  # caller (hybrid_agent) will fall back to direct LLM
        # Extract last meaningful line if full step dump
        if final_answer.startswith("Step ") and "\n" in final_answer:
            lines = [ln for ln in final_answer.split("\n") if ln.strip()]
            for ln in reversed(lines):
                if not ln.startswith("Step ") and not ln.startswith("Terminated"):
                    final_answer = ln.replace("Step N: ", "")
                    break

        return AgentResponse(
            answer=final_answer,
            steps=steps,
            tools_used=list(dict.fromkeys(tools_used)),
            verified=True,
            total_iterations=iteration or len(steps),
        )

    async def _cancel(self, req_id: str) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps({"type": "cancel", "id": req_id}))
        except Exception:
            pass


_bridge_client: ManusBridgeClient | None = None


def get_bridge_client() -> ManusBridgeClient:
    global _bridge_client
    if _bridge_client is None:
        _bridge_client = ManusBridgeClient()
    return _bridge_client
