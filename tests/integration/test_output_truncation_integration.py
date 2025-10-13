"""Integration test for output truncation and telemetry flags."""
from __future__ import annotations

import json

from agent import Tool
from agent_runner import AgentRunOptions, AgentRunner
from session import SessionSettings
from tests.integration.helpers import queue_tool_turn
from tests.mocking import MockAnthropic
from tools_run_terminal_cmd import run_terminal_cmd_tool_def, run_terminal_cmd_impl


def test_run_terminal_cmd_output_truncation(integration_workspace) -> None:
    client = MockAnthropic()
    queue_tool_turn(
        client,
        tool_name="run_terminal_cmd",
        payloads=[{
            "command": "python -c \"import sys\nfor i in range(1000): print('line', i)\"",
            "is_background": False,
        }],
        final_text="Captured logs.",
    )

    settings = SessionSettings()
    runner = AgentRunner(
        tools=[_build_shell_tool()],
        options=AgentRunOptions(max_turns=1, verbose=False),
        client=client,
        session_settings=settings,
    )

    result = runner.run("Produce long output")

    assert result.tool_events, "expected tool event from command"
    event = result.tool_events[0]
    body = json.loads(event.result)
    assert "omitted" in body["output"]
    assert body["metadata"]["timed_out"] is False
    assert body["metadata"]["truncated"] is True
    assert event.metadata.get("truncated") is True

    assert runner.context is not None
    telemetry = runner.context.telemetry
    assert telemetry.tool_executions, "expected telemetry records"
    assert telemetry.tool_executions[0].truncated is True
def _build_shell_tool() -> Tool:
    definition = run_terminal_cmd_tool_def()
    return Tool(
        name=definition["name"],
        description=definition["description"],
        input_schema=definition["input_schema"],
        fn=run_terminal_cmd_impl,
        capabilities={"exec_shell"},
    )
