"""Integration tests for MCP client pooling and dynamic tool registration."""
from __future__ import annotations

import asyncio
from dataclasses import replace

from agent_runner import AgentRunOptions, AgentRunner
from session import SessionSettings, MCPServerDefinition
from tests.integration.helpers import StubMCPClient, StubMCPTool, queue_tool_turn
from tests.mocking import MockAnthropic


def test_mcp_pool_registers_and_invokes_tools(monkeypatch) -> None:
    tools = [StubMCPTool(name="echo", description="Echo input")]

    def _response(arguments):  # simple echo response
        text = arguments.get("text", "")
        return f"echo: {text}"

    stub_client = StubMCPClient(name="stub", tools=tools, responses={"echo": _response})

    async def fake_connect(definition: MCPServerDefinition) -> StubMCPClient:
        assert definition.name == "stub"
        return stub_client

    monkeypatch.setattr("tools.mcp_client.connect_stdio_server", fake_connect)
    monkeypatch.setattr("agent_runner.connect_stdio_server", fake_connect)

    definition = MCPServerDefinition(name="stub", command="stub", args=())
    base_settings = SessionSettings()
    mcp_settings = replace(base_settings.mcp, definitions=(definition,))
    settings = replace(base_settings, mcp=mcp_settings)

    client = MockAnthropic()
    queue_tool_turn(
        client,
        tool_name="stub/echo",
        payloads=[{"text": "ping"}, {"text": "pong"}],
        final_text="Finished MCP calls.",
    )

    runner = AgentRunner(
        tools=[],
        options=AgentRunOptions(max_turns=1, verbose=False),
        client=client,
        session_settings=settings,
    )

    result = runner.run("Use MCP echo tool twice")

    assert stub_client.calls == [
        ("echo", {"text": "ping"}),
        ("echo", {"text": "pong"}),
    ]

    # Ensure registry recorded MCP tool events
    tool_names = [event.tool_name for event in result.tool_events]
    assert tool_names == ["stub/echo", "stub/echo"]
    assert all("echo:" in event.result for event in result.tool_events)

    asyncio.run(stub_client.aclose())
