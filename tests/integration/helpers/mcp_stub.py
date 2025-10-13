"""Minimal MCP stdio stub server for integration tests."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional, Tuple

from session.settings import MCPServerDefinition


@dataclass
class StubMCPTool:
    name: str
    description: str = ""
    input_schema: Dict[str, Any] | None = None


class StubMCPClient:
    """Simple MCP client implementation used for pooling tests."""

    def __init__(self, name: str, tools: Iterable[StubMCPTool], responses: Dict[str, Any]) -> None:
        self._name = name
        self._tools = list(tools)
        self._responses = dict(responses)
        self._closed = False
        self.calls: List[Tuple[str, Dict[str, Any]]] = []

    async def is_healthy(self) -> bool:
        return not self._closed

    async def aclose(self) -> None:
        self._closed = True

    async def list_tools(self) -> Any:
        if self._closed:
            raise RuntimeError("client closed")
        return SimpleNamespace(
            tools=[
                SimpleNamespace(
                    name=tool.name,
                    description=tool.description,
                    inputSchema=tool.input_schema or {"type": "object", "properties": {}},
                )
                for tool in self._tools
            ]
        )

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        if self._closed:
            raise RuntimeError("client closed")
        self.calls.append((name, dict(arguments)))
        handler = self._responses.get(name)
        if handler is None:
            raise KeyError(f"no stubbed response for tool '{name}'")
        if callable(handler):
            result = handler(arguments)
            if asyncio.iscoroutine(result):
                result = await result
            return _normalize_result(result)
        return _normalize_result(handler)


@asynccontextmanager
async def mcp_stub_server(
    *,
    name: str = "stub",
    tools: Optional[Iterable[StubMCPTool]] = None,
    responses: Optional[Dict[str, Any]] = None,
    command: str = "echo",
    args: Optional[List[str]] = None,
) -> AsyncIterator[tuple[MCPServerDefinition, StubMCPClient]]:
    """Provide an MCP server definition and stub client for tests.

    The caller is expected to monkeypatch ``tools.mcp_client.connect_stdio_server``
    to return the yielded ``StubMCPClient`` when invoked with the provided
    definition.
    """

    definition = MCPServerDefinition(
        name=name,
        command=command,
        args=tuple(args or []),
        env=(),
    )
    client = StubMCPClient(name=name, tools=tools or [], responses=responses or {})
    try:
        yield definition, client
    finally:
        await client.aclose()


def _normalize_result(result: Any) -> Any:
    if isinstance(result, SimpleNamespace):
        return result
    if isinstance(result, str):
        return SimpleNamespace(content=[SimpleNamespace(text=result)], isError=False)
    if isinstance(result, dict):
        if "content" in result and isinstance(result["content"], list):
            return SimpleNamespace(
                content=[SimpleNamespace(text=str(item)) for item in result["content"]],
                isError=bool(result.get("is_error") or result.get("isError")),
            )
        text = result.get("text") or result.get("output")
        return SimpleNamespace(
            content=[SimpleNamespace(text=str(text))] if text is not None else [],
            isError=bool(result.get("is_error") or result.get("isError")),
        )
    return result


__all__ = ["StubMCPTool", "StubMCPClient", "mcp_stub_server"]
