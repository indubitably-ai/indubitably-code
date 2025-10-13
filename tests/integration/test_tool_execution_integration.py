"""Integration coverage for core tool behaviors."""
from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path

from agent import Tool
from agent_runner import AgentRunOptions, AgentRunner
from session import SessionSettings
from tests.integration.helpers import queue_tool_turn
from tests.mocking import MockAnthropic, text_block, tool_use_block

from tools_apply_patch import apply_patch_tool_def, apply_patch_impl
from tools_glob_file_search import glob_file_search_tool_def, glob_file_search_impl
from tools_grep import grep_tool_def, grep_impl
from tools_list import list_files_tool_def, list_files_impl
from tools_read import read_file_tool_def, read_file_impl
from tools_run_terminal_cmd import run_terminal_cmd_tool_def, run_terminal_cmd_impl


def _tool_from_def(tool_def: dict, fn, capabilities: set[str]) -> Tool:
    return Tool(
        name=tool_def["name"],
        description=tool_def["description"],
        input_schema=tool_def["input_schema"],
        fn=fn,
        capabilities=capabilities,
    )


def test_runner_lists_and_reads_files(integration_workspace) -> None:
    """AgentRunner should combine list/read tools to surface workspace contents."""

    integration_workspace.write("src/main.py", "print('hi')\n")
    integration_workspace.write("README.md", "sample docs\n")

    list_tool = _tool_from_def(list_files_tool_def(), list_files_impl, {"read_fs"})
    read_tool = _tool_from_def(read_file_tool_def(), read_file_impl, {"read_fs"})

    client = MockAnthropic()
    client.add_response_from_blocks(
        [
            text_block("Listing files then reading README."),
            tool_use_block(
                "list_files",
                {"path": ".", "include_dirs": False},
                tool_use_id="call-1",
            ),
            tool_use_block(
                "read_file",
                {"path": "README.md"},
                tool_use_id="call-2",
            ),
        ]
    )
    client.add_response_from_blocks([text_block("Listed files and read README.")])

    runner = AgentRunner(
        tools=[list_tool, read_tool],
        options=AgentRunOptions(max_turns=4, verbose=False),
        client=client,
    )

    result = runner.run("List project files and read the README.")

    assert any(event.tool_name == "list_files" for event in result.tool_events)
    assert any(event.tool_name == "read_file" for event in result.tool_events)

    list_event = next(event for event in result.tool_events if event.tool_name == "list_files")
    listed = json.loads(list_event.result)
    assert "README.md" in listed
    assert "src/main.py" in listed

    read_event = next(event for event in result.tool_events if event.tool_name == "read_file")
    assert "sample docs" in read_event.result


def test_runner_grep_reports_matches(integration_workspace) -> None:
    """Grep tool should locate pattern matches within the workspace."""

    integration_workspace.write("docs/plan.txt", "integration goals\nparallel execution\n")
    integration_workspace.write("docs/notes.txt", "miscellaneous\n")

    grep_tool = _tool_from_def(grep_tool_def(), grep_impl, {"read_fs"})

    client = MockAnthropic()
    queue_tool_turn(
        client,
        tool_name="grep",
        payloads=[{"pattern": "integration", "path": "docs"}],
        final_text="Reported matches.",
    )

    runner = AgentRunner(
        tools=[grep_tool],
        options=AgentRunOptions(max_turns=2, verbose=False),
        client=client,
    )

    result = runner.run("Search docs/ for the word integration.")

    assert result.tool_events
    match_event = result.tool_events[0]
    matches = json.loads(match_event.result)
    assert any("plan.txt" in line for line in matches)


def test_glob_file_search_finds_matching_files(integration_workspace) -> None:
    integration_workspace.write("src/main.py", "print('hi')\n")
    integration_workspace.write("src/app.ts", "console.log('hi')\n")
    integration_workspace.write("README.md", "docs\n")

    glob_tool = _tool_from_def(glob_file_search_tool_def(), glob_file_search_impl, {"read_fs"})

    client = MockAnthropic()
    queue_tool_turn(
        client,
        tool_name="glob_file_search",
        payloads=[{"target_directory": "src", "glob_pattern": "*.py"}],
        final_text="Found matches.",
    )

    runner = AgentRunner(
        tools=[glob_tool],
        options=AgentRunOptions(max_turns=1, verbose=False),
        client=client,
    )

    result = runner.run("Find python files")

    output = json.loads(result.tool_events[0].result)
    assert any(path.endswith("src/main.py") for path in output)
    assert all(path.endswith(".py") for path in output)


def test_runner_applies_patch_and_updates_file(integration_workspace) -> None:
    """apply_patch tool should modify files inside the runner workspace."""

    target = integration_workspace.write("notes.txt", "remember the milk\n")

    patch_text = """*** Update File: notes.txt
- remember the milk
+ remember the oat milk
"""

    patch_tool = _tool_from_def(apply_patch_tool_def(), apply_patch_impl, {"write_fs"})

    client = MockAnthropic()
    queue_tool_turn(
        client,
        tool_name="apply_patch",
        payloads=[{"file_path": "notes.txt", "patch": patch_text}],
        final_text="Patched the file.",
    )

    runner = AgentRunner(
        tools=[patch_tool],
        options=AgentRunOptions(max_turns=2, verbose=False),
        client=client,
    )

    result = runner.run("Update notes.txt contents.")

    assert target.read_text(encoding="utf-8") == "remember the oat milk\n"
    event = result.tool_events[0]
    payload = json.loads(event.result)
    assert payload["ok"] is True
    assert payload["action"].lower() == "update"
    assert "notes.txt" in payload["path"]


def test_run_terminal_cmd_background_creates_logs(integration_workspace) -> None:
    """Background shell commands should produce log files and metadata."""

    shell_tool = _tool_from_def(run_terminal_cmd_tool_def(), run_terminal_cmd_impl, {"exec_shell"})

    client = MockAnthropic()
    queue_tool_turn(
        client,
        tool_name="run_terminal_cmd",
        payloads=[{"command": "echo integration background", "is_background": True}],
        final_text="Command dispatched.",
    )

    runner = AgentRunner(
        tools=[shell_tool],
        options=AgentRunOptions(max_turns=2, verbose=False),
        client=client,
    )

    result = runner.run("Run background echo command.")

    event = result.tool_events[0]
    body = json.loads(event.result)
    assert body["metadata"]["timed_out"] is False
    assert not event.metadata.get("truncated", False)
    summary = body["output"].splitlines()
    assert any(line.startswith("background command dispatched") for line in summary)

    stdout_line = next(line for line in summary if line.startswith("stdout_log:"))
    stderr_line = next(line for line in summary if line.startswith("stderr_log:"))

    stdout_path = Path(stdout_line.split(":", 1)[1].strip())
    stderr_path = Path(stderr_line.split(":", 1)[1].strip())

    # Allow the background process a brief moment to flush logs.
    for _ in range(20):
        if stdout_path.exists() and stderr_path.exists():
            break
        time.sleep(0.025)

    assert stdout_path.exists()
    assert stderr_path.exists()

    for _ in range(20):
        contents = stdout_path.read_text(encoding="utf-8")
        if "integration background" in contents:
            break
        time.sleep(0.025)

    assert "integration background" in stdout_path.read_text(encoding="utf-8")

    assert runner.context is not None
    telemetry = runner.context.telemetry
    assert telemetry.tool_executions, "expected telemetry events"
    assert telemetry.tool_executions[0].truncated is False


def test_run_terminal_cmd_foreground_timeout_enforced(integration_workspace) -> None:
    """Foreground commands should respect execution timeout caps."""

    shell_tool = _tool_from_def(run_terminal_cmd_tool_def(), run_terminal_cmd_impl, {"exec_shell"})

    client = MockAnthropic()
    queue_tool_turn(
        client,
        tool_name="run_terminal_cmd",
        payloads=[{"command": "sleep 1", "is_background": False, "timeout": 5}],
        final_text="Command timed out.",
    )

    base_settings = SessionSettings()
    execution = replace(base_settings.execution, timeout_seconds=0.1)
    settings = replace(base_settings, execution=execution)

    runner = AgentRunner(
        tools=[shell_tool],
        options=AgentRunOptions(max_turns=1, verbose=False),
        client=client,
        session_settings=settings,
    )

    result = runner.run("Foreground timeout test")

    body = json.loads(result.tool_events[0].result)
    assert body["metadata"]["timed_out"] is True
