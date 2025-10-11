import json

from agent import Tool
from tests.harness.test_agent import test_agent
from tests.mocking import (
    MockAnthropicServer,
    ev_message_stop,
    ev_tool_use,
    text_block,
    tool_use_block,
)


def _make_tool(name="echo") -> Tool:
    return Tool(
        name=name,
        description="",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        fn=lambda payload: json.dumps({"ok": True, "path": payload.get("path")}),
    )


def test_mock_anthropic_server_records_tool_results():
    server = MockAnthropicServer()
    tool = _make_tool()

    server.add_response([
        ev_tool_use("call-1", tool.name, {"path": "note.txt"}),
        ev_message_stop(),
    ])
    server.add_response_from_blocks([
        text_block("done"),
    ])

    agent = test_agent().add_tool(tool).with_client(server.client).build()

    try:
        result = agent.run_turn("Please update")
        assert result.final_response == "done"
        block = server.get_tool_result("call-1")
        assert block["type"] == "tool_result"
        payload = json.loads(block["content"])
        assert payload["ok"] is True
        assert payload["path"] == "note.txt"
    finally:
        agent.cleanup()
        server.reset()
