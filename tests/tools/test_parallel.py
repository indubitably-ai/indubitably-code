import asyncio
import time

from tools import ToolCall, ToolPayload
from tools.parallel import ToolCallRuntime


class FakeRouter:
    def __init__(self, parallel_names):
        self.parallel_names = set(parallel_names)
        self.calls = []

    def tool_supports_parallel(self, name: str) -> bool:
        return name in self.parallel_names

    async def dispatch_tool_call(self, *, session, turn_context, tracker, sub_id, call: ToolCall):
        self.calls.append((call.tool_name, call.call_id))
        await asyncio.sleep(0.1)
        return {"type": "tool_result", "tool_use_id": call.call_id, "content": "", "is_error": False}


def test_parallel_tools_execute_concurrently():
    router = FakeRouter({"parallel"})
    runtime = ToolCallRuntime(router)

    call1 = ToolCall("parallel", "call-1", ToolPayload.function({}))
    call2 = ToolCall("parallel", "call-2", ToolPayload.function({}))

    async def run() -> float:
        start = time.perf_counter()
        await asyncio.gather(
            runtime.execute_tool_call(session=None, turn_context=None, tracker=None, sub_id="sub", call=call1),
            runtime.execute_tool_call(session=None, turn_context=None, tracker=None, sub_id="sub", call=call2),
        )
        return time.perf_counter() - start

    duration = asyncio.run(run())

    assert duration < 0.18  # roughly one sleep period
    assert len(router.calls) == 2


def test_sequential_tools_execute_serially():
    router = FakeRouter(set())
    runtime = ToolCallRuntime(router)

    call1 = ToolCall("serial", "call-1", ToolPayload.function({}))
    call2 = ToolCall("serial", "call-2", ToolPayload.function({}))

    async def run() -> float:
        start = time.perf_counter()
        await asyncio.gather(
            runtime.execute_tool_call(session=None, turn_context=None, tracker=None, sub_id="sub", call=call1),
            runtime.execute_tool_call(session=None, turn_context=None, tracker=None, sub_id="sub", call=call2),
        )
        return time.perf_counter() - start

    duration = asyncio.run(run())

    assert duration >= 0.2  # two sleeps sequentially
