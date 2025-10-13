"""Integration tests for execution and approval policies."""
from __future__ import annotations

import json

from agent import Tool
from agent_runner import AgentRunOptions, AgentRunner
from session import ContextSession, SessionSettings
from tests.integration.helpers import queue_tool_turn
from tests.mocking import MockAnthropic

from tools_run_terminal_cmd import run_terminal_cmd_tool_def, run_terminal_cmd_impl


def _build_shell_tool() -> Tool:
    definition = run_terminal_cmd_tool_def()
    return Tool(
        name=definition["name"],
        description=definition["description"],
        input_schema=definition["input_schema"],
        fn=run_terminal_cmd_impl,
        capabilities={"exec_shell"},
    )


def test_shell_command_blocked_by_policy(integration_workspace) -> None:
    """Blocked command patterns should surface as tool errors."""

    settings = SessionSettings().update_with(**{"execution.blocked_commands": "echo"})
    settings = settings.update_with(**{"execution.approval": "never"})
    assert settings.execution.blocked_commands == ("echo",)

    client = MockAnthropic()
    queue_tool_turn(
        client,
        tool_name="run_terminal_cmd",
        payloads=[{"command": "echo forbidden", "is_background": False}],
        final_text="Command rejected.",
        preamble_text="I'll run the command now.",
    )

    runner = AgentRunner(
        tools=[_build_shell_tool()],
        options=AgentRunOptions(max_turns=2, verbose=False),
        client=client,
        session_settings=settings,
    )

    result = runner.run("Execute echo forbidden (should be blocked).")

    assert runner.context is not None
    assert runner.context.exec_context.blocked_commands == ("echo",)

    event = result.tool_events[0]
    assert event.is_error is True
    assert "blocked" in event.result


def test_shell_command_requires_approval(integration_workspace, monkeypatch) -> None:
    """Approval policy should gate command execution and record the decision."""

    approvals = []

    def approval_stub(self, *, tool_name: str, command: str) -> bool:
        approvals.append((tool_name, command))
        return tool_name == "run_terminal_cmd" and command == "echo approved"  # approve once

    monkeypatch.setattr(ContextSession, "request_approval", approval_stub, raising=False)

    settings = SessionSettings().update_with(
        **{
            "execution.approval": "always",
        }
    )

    client = MockAnthropic()
    queue_tool_turn(
        client,
        tool_name="run_terminal_cmd",
        payloads=[{"command": "echo approved", "is_background": False}],
        final_text="Command success.",
        preamble_text="Requesting approval.",
    )

    runner = AgentRunner(
        tools=[_build_shell_tool()],
        options=AgentRunOptions(max_turns=2, verbose=False),
        client=client,
        session_settings=settings,
    )

    result = runner.run("Run echo approved with approval required.")

    assert approvals == [("run_terminal_cmd", "echo approved")]
    output = json.loads(result.tool_events[0].result)
    assert "approved" in output.get("output", "")


def test_shell_write_blocked_outside_allowed_path(integration_workspace) -> None:
    """Sandbox allowed paths should prevent writes outside the workspace."""

    settings = SessionSettings().update_with(**{"execution.allowed_paths": (integration_workspace.root,)})
    settings = settings.update_with(**{"execution.sandbox": "strict"})

    client = MockAnthropic()
    queue_tool_turn(
        client,
        tool_name="run_terminal_cmd",
        payloads=[{"command": "touch /tmp/forbidden.txt", "is_background": False}],
        final_text="Command rejected by sandbox.",
    )

    runner = AgentRunner(
        tools=[_build_shell_tool()],
        options=AgentRunOptions(max_turns=1, verbose=False),
        client=client,
        session_settings=settings,
    )

    result = runner.run("Attempt to write outside allowed paths.")

    event = result.tool_events[0]
    assert event.is_error is True
    assert "blocked" in event.result
    assert event.metadata.get("error_type") is not None or event.result
