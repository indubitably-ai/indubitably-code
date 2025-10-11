import asyncio
import json

from agent import Tool
from tools.handler import ToolInvocation
from tools.handlers.function import FunctionToolHandler
from tools.legacy import build_registry_from_tools, tool_specs_from_tools
from tools.payload import ToolPayload


def _make_tool(name="echo", capabilities=None) -> Tool:
    def impl(payload):
        return json.dumps({"ok": True, "payload": payload})

    return Tool(
        name=name,
        description="Echo tool",
        input_schema={"type": "object"},
        fn=impl,
        capabilities=capabilities,
    )


def test_function_handler_executes_tool_synchronously():
    tool = _make_tool()
    handler = FunctionToolHandler(tool)
    invocation = ToolInvocation(
        session=None,
        turn_context=type("Ctx", (), {})(),
        tracker=None,
        sub_id="sub",
        call_id="call-1",
        tool_name=tool.name,
        payload=ToolPayload.function({"value": 42}),
    )

    result = asyncio.run(handler.handle(invocation))
    assert result.success is True
    assert json.loads(result.content)["payload"] == {"value": 42}


def test_function_handler_returns_error_on_invalid_input():
    tool = _make_tool("run_terminal_cmd")
    handler = FunctionToolHandler(tool)
    invocation = ToolInvocation(
        session=None,
        turn_context=type("Ctx", (), {})(),
        tracker=None,
        sub_id="sub",
        call_id="call-err",
        tool_name=tool.name,
        payload=ToolPayload.function({"command": "rm -rf /"}),
    )

    result = asyncio.run(handler.handle(invocation))
    assert result.success is False
    assert "dangerous" in result.content


def test_build_registry_from_tools():
    tool = _make_tool(capabilities=set())
    specs, registry = build_registry_from_tools([tool])

    assert specs[0].spec.name == tool.name
    assert specs[0].supports_parallel is True


def test_build_registry_marks_mutating_tools_serial():
    tool = _make_tool(capabilities={"write_fs"})
    specs, registry = build_registry_from_tools([tool])
    assert specs[0].supports_parallel is False
    invocation = ToolInvocation(
        session=None,
        turn_context=type("Ctx", (), {})(),
        tracker=None,
        sub_id="sub",
        call_id="call-1",
        tool_name=tool.name,
        payload=ToolPayload.function({}),
    )
    result = asyncio.run(registry.dispatch(invocation))
    assert result.success is True


def test_tool_specs_from_tools():
    tool = _make_tool()
    specs = tool_specs_from_tools([tool])
    assert specs[0].name == tool.name
    assert specs[0].description == tool.description
