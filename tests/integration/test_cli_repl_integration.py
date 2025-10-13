"""Integration tests covering the interactive CLI harness."""
from __future__ import annotations

from pathlib import Path

from agent import Tool, run_agent
from tests.integration.helpers import ReplDriver, queue_tool_turn

from tools_read import read_file_tool_def, read_file_impl


def _build_read_file_tool() -> Tool:
    definition = read_file_tool_def()
    return Tool(
        name=definition["name"],
        description=definition["description"],
        input_schema=definition["input_schema"],
        fn=read_file_impl,
        capabilities={"read_fs"},
    )


def test_repl_reads_file_and_returns_contents(
    integration_workspace,
    anthropic_mock,
    stdin_stub,
    fake_figlet,
    capsys,
) -> None:
    """Simulate a user prompt that triggers a read-file tool call."""

    note_path = integration_workspace.write("notes/todo.txt", "remember the milk\n")

    client = anthropic_mock.patch("agent.Anthropic")
    client.reset()
    queue_tool_turn(
        client,
        tool_name="read_file",
        payloads=[{"path": str(Path("notes/todo.txt"))}],
        final_text="The file contains: remember the milk",
        preamble_text="Sure, I'll read that file.",
    )

    stdin_stub("Please show me notes/todo.txt\n", "\n")

    run_agent([
        _build_read_file_tool(),
    ], use_color=False)

    captured = capsys.readouterr()
    assert "You ▸" in captured.out
    assert "remember the milk" in captured.out
    assert note_path.exists()


def test_repl_handles_slash_commands_and_status(
    integration_workspace,
    anthropic_mock,
    stdin_stub,
    fake_figlet,
    capsys,
) -> None:
    """Ensure slash commands execute without contacting Anthropic."""

    client = anthropic_mock.patch("agent.Anthropic")
    client.reset()

    stdin_stub("/status\n", "\n")

    run_agent([], use_color=False)

    captured = capsys.readouterr()
    assert "Tokens:" in captured.out
    assert "Auto-compaction" in captured.out
    assert not client.requests


def test_repl_compact_and_pin_commands(
    integration_workspace,
    anthropic_mock,
    fake_figlet,
) -> None:
    transcript_path = integration_workspace.path("transcript.log")
    driver = ReplDriver()

    client = anthropic_mock.patch("agent.Anthropic")
    client.reset()

    result = driver.run(
        tools=[],
        user_commands=[
            "/pin add keep this note",
            "/status",
            "/compact",
        ],
        transcript_path=transcript_path,
        use_color=False,
    )

    output = result.stdout
    assert "Pinned" in output
    assert "Tokens:" in output
    assert "Compaction" in output
    assert transcript_path.exists()
    transcript = transcript_path.read_text(encoding="utf-8")
    assert "COMMAND: Pinned" in transcript
    assert "COMMAND: Compaction" in transcript
    assert not client.requests
