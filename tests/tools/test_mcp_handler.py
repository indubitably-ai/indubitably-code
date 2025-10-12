import asyncio
from types import SimpleNamespace

import pytest

from tools.handlers.mcp_handler import MCPHandler
from tools.handler import ToolInvocation
from tools.payload import ToolPayload


class FakeClient:
    def __init__(self, content=None, is_error=False, raise_exc=False):
        self._content = content or []
        self._is_error = is_error
        self._raise = raise_exc

    async def call_tool(self, tool, arguments):
        if self._raise:
            raise RuntimeError("boom")
        return SimpleNamespace(content=self._content, isError=self._is_error)


class FakeItem:
    def __init__(self, text):
        self.text = text


async def _invoke(handler, session, payload):
    invocation = ToolInvocation(
        session=session,
        turn_context=SimpleNamespace(),
        tracker=None,
        sub_id="test",
        call_id="call",
        tool_name="server/tool",
        payload=payload,
    )
    return await handler.handle(invocation)


def test_mcp_handler_success():
    handler = MCPHandler()
    payload = ToolPayload.mcp("server", "tool", {"value": 1})

    async def get_client(server_name):
        assert server_name == "server"
        return FakeClient([FakeItem("hello"), FakeItem("world")])

    session = SimpleNamespace(get_mcp_client=get_client)

    result = asyncio.run(_invoke(handler, session, payload))
    assert result.success is True
    assert result.content == "hello\nworld"


def test_mcp_handler_missing_client_method():
    handler = MCPHandler()
    payload = ToolPayload.mcp("server", "tool", {})
    session = SimpleNamespace()

    result = asyncio.run(_invoke(handler, session, payload))
    assert result.success is False
    assert "Session" in result.content


def test_mcp_handler_client_returns_none():
    handler = MCPHandler()
    payload = ToolPayload.mcp("server", "tool", {})

    async def get_client(server_name):
        return None

    session = SimpleNamespace(get_mcp_client=get_client)
    result = asyncio.run(_invoke(handler, session, payload))
    assert result.success is False
    assert "not available" in result.content


def test_mcp_handler_propagates_error_flag():
    handler = MCPHandler()
    payload = ToolPayload.mcp("server", "tool", {})

    async def get_client(server_name):
        return FakeClient([FakeItem("error occurred")], is_error=True)

    session = SimpleNamespace(get_mcp_client=get_client)
    result = asyncio.run(_invoke(handler, session, payload))
    assert result.success is False
    assert "error occurred" in result.content


def test_mcp_handler_exception_from_client():
    handler = MCPHandler()
    payload = ToolPayload.mcp("server", "tool", {})

    async def get_client(server_name):
        return FakeClient(raise_exc=True)

    session = SimpleNamespace(get_mcp_client=get_client)
    result = asyncio.run(_invoke(handler, session, payload))
    assert result.success is False
    assert "failed" in result.content


def test_mcp_handler_rejects_non_mcp_payload():
    handler = MCPHandler()
    payload = ToolPayload.function({})
    session = SimpleNamespace(get_mcp_client=lambda _: None)
    result = asyncio.run(_invoke(handler, session, payload))
    assert result.success is False
    assert "non-MCP" in result.content
