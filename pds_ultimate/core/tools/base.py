"""Tool abstraction — OpenAI function-calling compatible."""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class ToolResult:
    success: bool
    output: str
    error: str = ""
    artifacts: list[dict[str, Any]] = field(default_factory=list)

    def to_observation(self) -> str:
        if self.success:
            out = (self.output or "").strip()
            if out.upper().startswith("OK:"):
                return out
            return f"OK: {out}" if out else "OK"
        return f"ERROR: {self.error or self.output}"


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Awaitable[ToolResult]]
    category: str = "general"
    risk: str = "low"  # low | medium | high

    def to_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    async def run(self, **params: Any) -> ToolResult:
        try:
            return await self.handler(**params)
        except Exception as exc:
            logger_msg = traceback.format_exc()
            return ToolResult(
                success=False,
                output="",
                error=f"{type(exc).__name__}: {exc}\n{logger_msg}",
            )
