import json

from pathlib import Path

from agent import Tool
from agent_runner import AgentRunOptions
from tests.harness.test_agent import test_agent
from tests.mocking import MockAnthropic, text_block, tool_use_block


def test_test_agent_builder_runs_isolated_tools():
    executed = []

    def impl(payload):
        executed.append(payload["path"])
        return json.dumps({"ok": True, "path": payload["path"]})

    tool = Tool(
        name="echo",
        description="",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        fn=impl,
    )

    client = MockAnthropic()
    client.add_response_from_blocks([
        tool_use_block("echo", {"path": "notes.txt"}, tool_use_id="call-1")
    ])
    client.add_response_from_blocks([text_block("done")])

    builder = test_agent().add_tool(tool).with_client(client)

    # Ensure options mutation works and paths live inside temp dirs
    def options_mutator(options: AgentRunOptions) -> None:
        options.max_turns = 2

    builder.with_options(options_mutator)

    agent = builder.build()

    try:
        result = agent.run_turn("Please update notes")
        assert executed == ["notes.txt"]
        assert result.final_response == "done"
        assert len(result.tool_events) == 1
        assert agent.options.max_turns == 2
        assert agent.options.audit_log_path is not None
        assert agent.options.audit_log_path.parent == Path(agent.work_dir.name)
    finally:
        agent.cleanup()
