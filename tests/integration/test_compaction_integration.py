"""Integration tests for context compaction and pin management."""
from __future__ import annotations

from agent_runner import AgentRunOptions, AgentRunner
from tests.integration.helpers import ReplDriver
from tests.mocking import MockAnthropic
from tools_read import read_file_tool_def, read_file_impl
from agent import Tool


def _build_read_tool() -> Tool:
    definition = read_file_tool_def()
    return Tool(
        name=definition["name"],
        description=definition["description"],
        input_schema=definition["input_schema"],
        fn=read_file_impl,
        capabilities={"read_fs"},
    )


def test_compaction_and_pin_status(integration_workspace, anthropic_mock, fake_figlet) -> None:
    driver = ReplDriver()
    transcript_path = integration_workspace.path("transcript.log")

    client = anthropic_mock.patch("agent.Anthropic")
    client.reset()

    result = driver.run(
        tools=[_build_read_tool()],
        user_commands=[
            "/pin add important note",
            "Show status please",
            "/compact",
        ],
        transcript_path=transcript_path,
        use_color=False,
    )

    assert "Pinned" in result.stdout
    assert "Compaction" in result.stdout

    transcript = transcript_path.read_text(encoding="utf-8")
    assert "COMMAND: Pinned" in transcript
    assert "COMMAND: Compaction" in transcript
