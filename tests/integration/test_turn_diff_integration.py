"""Integration tests for turn diff tracking and undo flows."""
from __future__ import annotations

from agent import Tool
from agent_runner import AgentRunOptions, AgentRunner
from tests.integration.helpers import queue_tool_turn
from tests.mocking import MockAnthropic
from tools_apply_patch import apply_patch_tool_def, apply_patch_impl


def _build_apply_patch_tool() -> Tool:
    definition = apply_patch_tool_def()
    return Tool(
        name=definition["name"],
        description=definition["description"],
        input_schema=definition["input_schema"],
        fn=apply_patch_impl,
        capabilities={"write_fs"},
    )


def test_turn_diff_records_edits_and_undo(integration_workspace) -> None:
    target = integration_workspace.write("note.txt", "original\n")

    patch = """*** Update File: note.txt\n- original\n+ updated\n"""

    client = MockAnthropic()
    queue_tool_turn(
        client,
        tool_name="apply_patch",
        payloads=[{"file_path": "note.txt", "patch": patch}],
        final_text="Updated the note.",
    )

    runner = AgentRunner(
        tools=[_build_apply_patch_tool()],
        options=AgentRunOptions(max_turns=1, verbose=False),
        client=client,
    )

    result = runner.run("Edit note")

    assert target.read_text(encoding="utf-8") == "updated\n"
    assert runner.turn_summaries and "note.txt" in runner.turn_summaries[0]["summary"]

    operations = runner.undo_last_turn()
    assert target.read_text(encoding="utf-8") == "original\n"
    assert operations
