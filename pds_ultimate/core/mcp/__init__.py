"""MCP (Model Context Protocol) client — connects to external MCP servers.

Gives pds_ultimate/EthanAgent access to any MCP-compliant tool server,
including future OpenClaw bridge and third-party integrations.

Usage:
    from pds_ultimate.core.mcp import mcp_manager
    await mcp_manager.connect_sse("http://localhost:3001/sse", "openclaw")
    # All tools discovered from the server are auto-registered in tool_registry
"""

from pds_ultimate.core.mcp.client import MCPManager, mcp_manager

__all__ = ["MCPManager", "mcp_manager"]
