"""Integration tests covering fatal tool errors and recovery behavior."""
from __future__ import annotations

from agent import Tool
from agent_runner import AgentRunOptions, AgentRunner
from errors import FatalToolError
from tests.integration.helpers import queue_tool_turn
from tests.mocking import MockAnthropic


def _build_fatal_tool() -> Tool:
    def fatal_fn(_payload):
        raise FatalToolError("fatal failure")

    return Tool(
        name="fatal_tool",
        description="Always raises a fatal error.",
        input_schema={"type": "object", "properties": {}},
        fn=fatal_fn,
        capabilities={"write_fs"},
    )


def test_fatal_tool_causes_runner_to_stop() -> None:
    client = MockAnthropic()
    queue_tool_turn(
        client,
        tool_name="fatal_tool",
        payloads=[{}],
        final_text="Should not reach here.",
    )

    runner = AgentRunner(
        tools=[_build_fatal_tool()],
        options=AgentRunOptions(max_turns=3, exit_on_tool_error=True, verbose=False),
        client=client,
    )

    result = runner.run("Trigger fatal tool")

    assert result.stopped_reason == "fatal_tool_error"
    assert result.turns_used == 1
    assert result.tool_events[0].metadata.get("error_type") == "fatal"
