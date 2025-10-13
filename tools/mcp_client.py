"""Helpers for establishing MCP client sessions over stdio."""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, Dict

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from session.settings import MCPServerDefinition


@dataclass
class PooledMCPClient:
    """Wrapper around a live MCP client session used by the pool."""

    name: str
    session: ClientSession
    _stack: AsyncExitStack

    async def is_healthy(self) -> bool:
        """Return whether the underlying MCP session responds to a ping."""

        try:
            await asyncio.wait_for(self.session.send_ping(), timeout=5)
            return True
        except Exception:
            return False

    async def aclose(self) -> None:
        await self._stack.aclose()

    async def list_tools(self) -> Any:
        return await self.session.list_tools()

    async def call_tool(self, *args: Any, **kwargs: Any) -> Any:
        return await self.session.call_tool(*args, **kwargs)


async def connect_stdio_server(definition: MCPServerDefinition) -> PooledMCPClient:
    """Launch the configured MCP server and return a pooled client handle."""

    parameters = StdioServerParameters(
        command=definition.command,
        args=list(definition.args),
        env=_definition_env(definition),
        cwd=str(definition.cwd) if definition.cwd else None,
        encoding=definition.encoding,
        encoding_error_handler=definition.encoding_errors,
        startup_timeout_ms=definition.startup_timeout_ms,
    )

    stack = AsyncExitStack()
    client_cm = stdio_client(parameters)
    read_stream, write_stream = await stack.enter_async_context(client_cm)
    session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
    await session.initialize()
    return PooledMCPClient(name=definition.name, session=session, _stack=stack)


def _definition_env(definition: MCPServerDefinition) -> Dict[str, str]:
    if not definition.env:
        return {}
    return {key: value for key, value in definition.env}


__all__ = ["PooledMCPClient", "connect_stdio_server"]
