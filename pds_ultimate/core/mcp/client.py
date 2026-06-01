"""MCP client — SSE + stdio transport, auto-registers tools in pds_ultimate's ToolRegistry.

Adapted from OpenManus app/tool/mcp.py, wired to pds_ultimate's tool system.
"""

from __future__ import annotations

import re
from contextlib import AsyncExitStack
from typing import Any

from pds_ultimate.config import logger
from pds_ultimate.core.tools.base import ToolResult, ToolSpec
from pds_ultimate.core.tools.registry import tool_registry


def _sanitize_name(name: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    return sanitized[:64] if len(sanitized) > 64 else sanitized


class _MCPToolHandler:
    """Wraps an MCP session call so it matches pds_ultimate's ToolSpec handler signature."""

    def __init__(self, session: Any, original_name: str) -> None:
        self._session = session
        self._original_name = original_name

    async def __call__(self, **kwargs: Any) -> ToolResult:
        try:
            result = await self._session.call_tool(self._original_name, kwargs)
            # MCP returns list of content items (TextContent, ImageContent, …)
            parts: list[str] = []
            for item in result.content:
                if hasattr(item, "text"):
                    parts.append(item.text)
            output = "\n".join(parts) if parts else "No output returned."
            return ToolResult(success=True, output=output)
        except Exception as exc:
            return ToolResult(success=False, output="", error=str(exc))


class MCPManager:
    """Manages connections to MCP servers and exposes their tools in ToolRegistry."""

    def __init__(self) -> None:
        self._sessions: dict[str, Any] = {}
        self._exit_stacks: dict[str, AsyncExitStack] = {}
        # server_id → list of tool names registered in tool_registry
        self._registered: dict[str, list[str]] = {}

    # ── connection helpers ────────────────────────────────────────────────────

    async def connect_sse(self, server_url: str, server_id: str = "") -> None:
        """Connect to an MCP server via SSE transport (HTTP stream)."""
        try:
            from mcp import ClientSession
            from mcp.client.sse import sse_client
        except ImportError:
            raise RuntimeError(
                "mcp package not installed. Run: pip install mcp"
            )

        if not server_url:
            raise ValueError("server_url is required")

        server_id = server_id or server_url

        if server_id in self._sessions:
            await self.disconnect(server_id)

        stack = AsyncExitStack()
        self._exit_stacks[server_id] = stack
        streams = await stack.enter_async_context(sse_client(url=server_url))
        session = await stack.enter_async_context(ClientSession(*streams))
        self._sessions[server_id] = session
        await self._init_tools(server_id)
        logger.info(f"MCP: connected to '{server_id}' via SSE ({server_url})")

    async def connect_stdio(
        self, command: str, args: list[str] | None = None, server_id: str = ""
    ) -> None:
        """Connect to an MCP server via stdio transport (subprocess)."""
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            raise RuntimeError(
                "mcp package not installed. Run: pip install mcp"
            )

        if not command:
            raise ValueError("command is required")

        server_id = server_id or command
        if server_id in self._sessions:
            await self.disconnect(server_id)

        stack = AsyncExitStack()
        self._exit_stacks[server_id] = stack
        params = StdioServerParameters(command=command, args=args or [])
        transport = await stack.enter_async_context(stdio_client(params))
        read, write = transport
        session = await stack.enter_async_context(ClientSession(read, write))
        self._sessions[server_id] = session
        await self._init_tools(server_id)
        logger.info(
            f"MCP: connected to '{server_id}' via stdio (cmd: {command})")

    # ── tool registration ─────────────────────────────────────────────────────

    async def _init_tools(self, server_id: str) -> None:
        session = self._sessions[server_id]
        await session.initialize()
        response = await session.list_tools()

        registered_names: list[str] = []
        for mcp_tool in response.tools:
            raw_name = f"mcp_{server_id}_{mcp_tool.name}"
            tool_name = _sanitize_name(raw_name)

            handler = _MCPToolHandler(session, mcp_tool.name)
            spec = ToolSpec(
                name=tool_name,
                description=f"[MCP:{server_id}] {mcp_tool.description or mcp_tool.name}",
                parameters=mcp_tool.inputSchema or {
                    "type": "object", "properties": {}},
                handler=handler,
                category="mcp",
                risk="medium",
            )
            tool_registry.register(spec)
            registered_names.append(tool_name)

        self._registered[server_id] = registered_names
        logger.info(
            f"MCP: registered {len(registered_names)} tools from '{server_id}': "
            f"{registered_names[:8]}{'...' if len(registered_names) > 8 else ''}"
        )

    # ── disconnect ────────────────────────────────────────────────────────────

    async def disconnect(self, server_id: str = "") -> None:
        """Disconnect from a server and unregister its tools."""
        if server_id:
            await self._disconnect_one(server_id)
        else:
            for sid in list(self._sessions.keys()):
                await self._disconnect_one(sid)

    async def _disconnect_one(self, server_id: str) -> None:
        stack = self._exit_stacks.pop(server_id, None)
        if stack:
            try:
                await stack.aclose()
            except RuntimeError as exc:
                if "cancel scope" not in str(exc).lower():
                    raise
                logger.warning(
                    f"MCP: cancel-scope error on disconnect from '{server_id}' (ignored): {exc}")
        self._sessions.pop(server_id, None)

        # Remove tools from registry
        for tool_name in self._registered.pop(server_id, []):
            tool_registry._tools.pop(tool_name, None)

        logger.info(f"MCP: disconnected from '{server_id}'")

    # ── info ─────────────────────────────────────────────────────────────────

    def connected_servers(self) -> list[str]:
        return list(self._sessions.keys())

    def tools_for(self, server_id: str) -> list[str]:
        return list(self._registered.get(server_id, []))

    async def list_all_tools(self) -> dict[str, list[str]]:
        """Return {server_id: [tool_names]} for all connected servers."""
        return {sid: self.tools_for(sid) for sid in self._sessions}


# Singleton
mcp_manager = MCPManager()
