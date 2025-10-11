from datetime import timedelta

from tests.harness.test_agent import test_agent
from tests.mocking import MockAnthropic, text_block, tool_use_block
from tests.testing_tools import make_sync_test_tool, reset_sync_tool_state
from tests.utils import assert_serial_execution, measure_sync_duration


def test_tool_executes_serially_with_mock_client():
    reset_sync_tool_state()
    tool = make_sync_test_tool()

    client = MockAnthropic()
    client.add_response_from_blocks(
        [
            tool_use_block(tool.name, {"sleep_after_ms": 200}, tool_use_id="call-1"),
            tool_use_block(tool.name, {"sleep_after_ms": 200}, tool_use_id="call-2"),
        ]
    )
    client.add_response_from_blocks([text_block("done")])

    agent = test_agent().add_tool(tool).with_client(client).build()

    try:
        duration = measure_sync_duration(lambda: agent.run_turn("perform two ops"))
        assert_serial_execution(duration, timedelta(milliseconds=200), count=2)
    finally:
        agent.cleanup()
        client.reset()
