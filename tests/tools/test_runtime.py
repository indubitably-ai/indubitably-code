import asyncio

from tools import ToolRuntime, ToolPayload
from tools.registry import ToolRegistry
from tools.handler import ToolOutput


class FakeRegistry(ToolRegistry):
    async def dispatch(self, invocation):  # type: ignore[override]
        return ToolOutput(content="ok", success=True)


def test_tool_runtime_dispatch_builds_tool_result():
    runtime = ToolRuntime(FakeRegistry({}))
    payload = ToolPayload.function({})
    result = asyncio.run(
        runtime.dispatch(
            session="session",
            turn_context="context",
            tracker="tracker",
            sub_id="sub",
            tool_name="echo",
            call_id="call-1",
            payload=payload,
        )
    )

    assert result.success is True
    assert result.output["type"] == "tool_result"
    assert result.output["tool_use_id"] == "call-1"
    assert result.output["is_error"] is False
