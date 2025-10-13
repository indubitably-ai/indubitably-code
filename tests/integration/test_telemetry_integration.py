"""Integration tests validating session telemetry output."""
from __future__ import annotations

import json

from agent import Tool
from agent_runner import AgentRunOptions, AgentRunner
from tests.integration.helpers import TelemetrySink, queue_tool_turn
from tests.mocking import MockAnthropic, text_block, tool_use_block
from tools_read import read_file_tool_def, read_file_impl
from tools_run_terminal_cmd import run_terminal_cmd_tool_def, run_terminal_cmd_impl
from session import SessionSettings
from dataclasses import replace


def _build_read_tool() -> Tool:
    definition = read_file_tool_def()
    return Tool(
        name=definition["name"],
        description=definition["description"],
        input_schema=definition["input_schema"],
        fn=read_file_impl,
        capabilities={"read_fs"},
    )


def _build_shell_tool() -> Tool:
    definition = run_terminal_cmd_tool_def()
    return Tool(
        name=definition["name"],
        description=definition["description"],
        input_schema=definition["input_schema"],
        fn=run_terminal_cmd_impl,
        capabilities={"exec_shell"},
    )


def test_telemetry_records_tool_execution(integration_workspace) -> None:
    """Running a tool should populate session telemetry and OTEL export."""

    integration_workspace.write("story.txt", "telemetry test\n")

    client = MockAnthropic()
    queue_tool_turn(
        client,
        tool_name="read_file",
        payloads=[{"path": "story.txt"}],
        final_text="Read complete.",
    )

    runner = AgentRunner(
        tools=[_build_read_tool()],
        options=AgentRunOptions(max_turns=2, verbose=False),
        client=client,
    )

    result = runner.run("Read story.txt")

    assert runner.context is not None
    telemetry = runner.context.telemetry

    assert telemetry.tool_executions, "expected telemetry events"
    event = telemetry.tool_executions[0]
    assert event.tool_name == "read_file"
    assert event.success is True

    stats = telemetry.tool_stats("read_file")
    assert stats["calls"] >= 1
    assert stats["errors"] == 0

    otel = json.loads(telemetry.export_otel())
    assert otel["events"][0]["attributes"]["tool.name"] == "read_file"

    sink = TelemetrySink()
    telemetry.flush_to_otel(sink)
    assert sink.events and sink.events[0].attributes["tool.name"] == "read_file"

    # Tool event payload should still reflect success for completeness.
    tool_event = result.tool_events[0]
    assert "telemetry test" in tool_event.result


def test_telemetry_captures_error_events(integration_workspace) -> None:
    client = MockAnthropic()
    client.add_response_from_blocks(
        [
            text_block("Running blocked command."),
            tool_use_block(
                "run_terminal_cmd",
                {"command": "echo forbidden", "is_background": False},
                tool_use_id="call-1",
            ),
        ]
    )
    client.add_response_from_blocks([text_block("Blocked by policy.")])

    base_settings = SessionSettings()
    execution = replace(base_settings.execution, blocked_commands=("echo",))
    settings = replace(base_settings, execution=execution)

    runner = AgentRunner(
        tools=[_build_shell_tool()],
        options=AgentRunOptions(max_turns=1, verbose=False),
        client=client,
        session_settings=settings,
    )

    result = runner.run("Run blocked command")

    telemetry = runner.context.telemetry  # type: ignore[union-attr]
    sink = TelemetrySink()
    telemetry.flush_to_otel(sink)

    assert any(event.attributes.get("tool.success") is False for event in sink.events)
    assert result.tool_events[0].is_error is True
