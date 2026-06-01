"""LLM engine compatibility layer — wraps new LLMClient."""

from __future__ import annotations

from typing import Any

from pds_ultimate.core.llm.client import llm_client
from pds_ultimate.core.llm.router import TaskKind


class LLMEngine:
    async def start(self) -> None:
        await llm_client.start()

    async def stop(self) -> None:
        await llm_client.stop()

    async def chat(
        self,
        messages: list[dict[str, str]],
        task_type: str = "simple_answer",
        **kwargs: Any,
    ) -> str:
        kind = TaskKind.REASON if task_type in {"agent", "complex", "parse_order"} else TaskKind.CHAT
        return await llm_client.chat(messages, kind=kind, **kwargs)

    async def chat_json(self, messages: list[dict[str, str]], **kwargs: Any) -> dict:
        return await llm_client.chat_json(messages, **kwargs)


llm_engine = LLMEngine()
