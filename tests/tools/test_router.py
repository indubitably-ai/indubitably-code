import asyncio

import pytest

from tools.handler import ToolOutput
from tools.payload import FunctionToolPayload, MCPToolPayload, ToolPayload
from tools.registry import ConfiguredToolSpec, ToolRegistry
from tools.router import ToolCall, ToolRouter
from tools.spec import ToolSpec


class _StubRegistry(ToolRegistry):
    async def dispatch(self, invocation):
        return invocation  # type: ignore[return-value]


def test_build_tool_call_for_function_payload():
    call = ToolRouter.build_tool_call(
        {
            "type": "tool_use",
            "name": "read_file",
            "id": "call-1",
            "input": {"path": "README.md"},
        }
    )
    assert call is not None
    assert call.tool_name == "read_file"
    assert call.call_id == "call-1"
    assert isinstance(call.payload, FunctionToolPayload)
    assert call.payload.arguments == {"path": "README.md"}


def test_build_tool_call_for_mcp_payload():
    call = ToolRouter.build_tool_call(
        {
            "type": "tool_use",
            "name": "server/tool",
            "id": "call-42",
            "input": {"arg": 1},
        }
    )
    assert call is not None
    assert call.tool_name == "server/tool"
    assert isinstance(call.payload, MCPToolPayload)
    assert call.payload.server == "server"
    assert call.payload.tool == "tool"
    assert call.payload.arguments == {"arg": 1}


def test_tool_supports_parallel_flag():
    registry = _StubRegistry({})
    specs = [
        ConfiguredToolSpec(ToolSpec("fast_tool", "", {}), supports_parallel=True),
        ConfiguredToolSpec(ToolSpec("slow_tool", "", {}), supports_parallel=False),
    ]
    router = ToolRouter(registry, specs)
    assert router.tool_supports_parallel("fast_tool") is True
    assert router.tool_supports_parallel("slow_tool") is False
    assert router.tool_supports_parallel("missing") is False


def test_dispatch_tool_call_constructs_invocation(monkeypatch):
    captured = {}

    class FakeRegistry(ToolRegistry):
        async def dispatch(self, invocation):  # type: ignore[override]
            captured["invocation"] = invocation
            return ToolOutput(content="ok", success=True)

    router = ToolRouter(FakeRegistry({}), [])
    call = ToolCall("echo", "call-1", ToolPayload.function({"value": 1}))

    result = asyncio.run(
        router.dispatch_tool_call(
            session="session",
            turn_context="ctx",
            tracker="tracker",
            sub_id="sub",
            call=call,
        )
    )

    assert result["type"] == "tool_result"
    assert result["tool_use_id"] == "call-1"
    assert result["is_error"] is False

    invocation = captured["invocation"]
    assert invocation.tool_name == "echo"
    assert invocation.call_id == "call-1"
    assert invocation.payload.kind.name.lower() == "function"
