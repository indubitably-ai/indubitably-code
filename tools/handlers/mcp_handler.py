"""Handler that delegates tool calls to MCP servers."""
from __future__ import annotations

from typing import Any

from tools.handler import ToolHandler, ToolInvocation, ToolKind, ToolOutput
from tools.payload import MCPToolPayload, ToolPayload


class MCPHandler(ToolHandler):
    """Adapter that proxies MCP tool calls to remote servers."""

    @property
    def kind(self) -> ToolKind:
        return ToolKind.MCP

    def matches_kind(self, payload: ToolPayload) -> bool:
        return isinstance(payload, MCPToolPayload)

    async def handle(self, invocation: ToolInvocation) -> ToolOutput:
        payload = invocation.payload
        if not isinstance(payload, MCPToolPayload):
            return ToolOutput(content="MCP handler received non-MCP payload", success=False)

        get_client = getattr(invocation.session, "get_mcp_client", None)
        if get_client is None:
            return ToolOutput(
                content="Session does not support MCP clients",
                success=False,
            )

        client = await get_client(payload.server)
        if client is None:
            return ToolOutput(
                content=f"MCP server '{payload.server}' not available",
                success=False,
            )

        try:
            result = await client.call_tool(payload.tool, payload.arguments)
        except Exception as exc:  # pragma: no cover - defensive
            mark_unhealthy = getattr(invocation.session, "mark_mcp_client_unhealthy", None)
            if mark_unhealthy is not None:
                await mark_unhealthy(payload.server)
            return ToolOutput(content=f"MCP tool call failed: {exc}", success=False)

        content = _collect_mcp_content(result)
        is_error = bool(getattr(result, "isError", False))
        return ToolOutput(content=content, success=not is_error)


def _collect_mcp_content(result: Any) -> str:
    parts: list[str] = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text:
            parts.append(text)
    if parts:
        return "\n".join(parts)
    fallback = getattr(result, "text", None)
    if fallback:
        return str(fallback)
    return ""


__all__ = ["MCPHandler"]
