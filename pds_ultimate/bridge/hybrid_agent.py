"""Hybrid agent — OpenManus via WebSocket IPC (OpenClaw-compatible interface)."""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable

from pds_ultimate.bridge.manus_client import get_bridge_client
from pds_ultimate.config import config, logger
from pds_ultimate.core.agent.ethan import EthanAgent
from pds_ultimate.core.agent.types import AgentResponse
from pds_ultimate.core.memory.hierarchy import hierarchical_memory

# Reuse ethan smalltalk fast-path only — main loop goes to OpenManus.
_ethan = EthanAgent()


class HybridManusAgent:
    """OpenManus brain over WS; PDS adds memory/context only."""

    async def should_use_tools(self, text: str) -> bool:
        return await _ethan.should_use_tools(text)

    async def direct_response(
        self,
        message: str,
        history: list[dict] | None = None,
        style_guide: str = "",
        chat_id: int = 0,
    ) -> str:
        return await _ethan.direct_response(message, history, style_guide, chat_id)

    async def background_extract_memories(self, dialogue: str, db_session: Any = None) -> None:
        await _ethan.background_extract_memories(dialogue, db_session)

    async def process(
        self,
        message: str,
        chat_id: int,
        history: list[dict] | None = None,
        db_session: Any = None,
        style_guide: str = "",
        step_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> AgentResponse:
        user_text = message
        memory_ctx = hierarchical_memory.build_context(chat_id, query=user_text)
        lessons = ""
        try:
            from pds_ultimate.core.agent.lessons import lesson_book

            lessons = lesson_book.recall(chat_id, user_text)
        except Exception:
            pass

        context = {
            "user_id": chat_id,
            "memory": memory_ctx,
            "lessons": lessons,
            "style_guide": style_guide,
            "history": (history or [])[-8:],
        }

        logger.info(f"HybridManus: IPC run chat={chat_id} msg={user_text[:60]!r}")
        client = get_bridge_client()
        result = await client.run(
            user_text,
            session_id=chat_id,
            context=context,
            step_callback=step_callback,
            timeout=float(config.limits.agent_wall_clock_sec),
        )

        try:
            _ethan.remember_turn(chat_id, "user", user_text)
            _ethan.remember_turn(chat_id, "assistant", result.answer)
            await hierarchical_memory.maybe_summarize_session(chat_id)
        except Exception as exc:
            logger.debug(f"post-run memory skipped: {exc}")

        return result


agent = HybridManusAgent()
