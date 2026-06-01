"""Central tool registry."""

from __future__ import annotations

from typing import Any

from pds_ultimate.core.tools.base import ToolResult, ToolSpec


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, tool: ToolSpec) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def list_tools(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def openai_schemas(self) -> list[dict[str, Any]]:
        return [t.to_openai_schema() for t in self._tools.values()]

    def description_block(self) -> str:
        lines: list[str] = []
        for tool in sorted(self._tools.values(), key=lambda t: (t.category, t.name)):
            params = tool.parameters.get("properties", {})
            param_names = ", ".join(params.keys()) if params else "—"
            lines.append(f"- **{tool.name}** [{tool.category}]: {tool.description} (params: {param_names})")
        return "\n".join(lines)

    async def execute(self, name: str, params: dict[str, Any] | None = None) -> ToolResult:
        tool = self.get(name)
        if not tool:
            return ToolResult(success=False, output="", error=f"Unknown tool: {name}")
        return await tool.run(**(params or {}))


tool_registry = ToolRegistry()
