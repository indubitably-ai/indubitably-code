import json
from pathlib import Path
import asyncio

import pytest

from agent import Tool
from agents_md import load_agents_md
from agent_runner import AgentRunOptions, AgentRunner
from tests.mocking import MockAnthropic, text_block, tool_use_block
from errors import FatalToolError
from session import MCPServerDefinition, MCPSettings, SessionSettings


def _make_tool(name="writer", capabilities=None, fn=None):
    def stub_fn(payload):
        return json.dumps({"path": payload.get("path"), "ok": True})

    return Tool(
        name=name,
        description="",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        fn=fn or stub_fn,
        capabilities=capabilities or {"write_fs"},
    )



def test_agent_runner_executes_tools_and_tracks_files(tmp_path):
    executed = []

    def impl(payload):
        executed.append(payload["path"])
        return "ok"

    tool = _make_tool(fn=impl)
    client = MockAnthropic()
    client.add_response_from_blocks(
        [tool_use_block(tool.name, {"path": "notes.txt"}, tool_use_id="tool-1")]
    )
    client.add_response_from_blocks([text_block("all done")])

    options = AgentRunOptions(max_turns=3, audit_log_path=tmp_path / "audit.jsonl", changes_log_path=tmp_path / "changes.jsonl")
    runner = AgentRunner([tool], options, client=client)

    result = runner.run("Please update notes")

    assert result.final_response == "all done"
    assert executed == ["notes.txt"]
    assert result.edited_files == ["notes.txt"]
    assert result.turn_summaries == []
    assert len(result.tool_events) == 1
    assert result.tool_events[0].tool_name == tool.name

    audit = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert audit and json.loads(audit[0])["tool"] == tool.name

    changes = (tmp_path / "changes.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert changes
    change_entry = json.loads(changes[0])
    if "path" in change_entry:
        assert change_entry["path"] == "notes.txt"
    else:
        assert "paths" in change_entry and "notes.txt" in change_entry["paths"]


def test_agent_runner_logs_turn_summaries(tmp_path):
    target_file = tmp_path / "summary.txt"

    def impl(payload, tracker):
        path = Path(payload["path"])
        content = payload.get("content", "generated\n")
        old_content = path.read_text(encoding="utf-8") if path.exists() else None
        if tracker is not None:
            tracker.lock_file(path)
        try:
            path.write_text(content, encoding="utf-8")
        finally:
            if tracker is not None:
                tracker.unlock_file(path)
        if tracker is not None:
            tracker.record_edit(
                path=path,
                tool_name="write_file",
                action="create" if old_content is None else "edit",
                old_content=old_content,
                new_content=content,
            )
        return "ok"

    tool = _make_tool(name="writer", fn=impl)
    client = MockAnthropic()
    client.add_response_from_blocks(
        [
            tool_use_block(
                tool.name,
                {"path": str(target_file), "content": "data\n"},
                tool_use_id="tool-1",
            )
        ]
    )
    client.add_response_from_blocks([text_block("all done")])

    options = AgentRunOptions(changes_log_path=tmp_path / "changes.jsonl")
    runner = AgentRunner([tool], options, client=client)

    result = runner.run("Write file")

    assert result.turn_summaries
    first_summary = result.turn_summaries[0]
    assert first_summary["paths"]
    assert str(target_file.name) in "\n".join(first_summary["paths"])

    log_entries = (tmp_path / "changes.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(log_entries) >= 2  # tool record + summary
    summary_entry = json.loads(log_entries[-1])
    assert summary_entry.get("turn") == 1
    assert "summary" in summary_entry


def test_agent_runner_undo_last_turn(tmp_path):
    target_file = tmp_path / "tracked.txt"
    target_file.write_text("initial", encoding="utf-8")

    def impl(payload, tracker):
        path = Path(payload["path"])
        old = path.read_text(encoding="utf-8") if path.exists() else None
        if tracker is not None:
            tracker.lock_file(path)
        try:
            path.write_text(payload.get("content", "updated"), encoding="utf-8")
        finally:
            if tracker is not None:
                tracker.unlock_file(path)
        if tracker is not None:
            tracker.record_edit(
                path=path,
                tool_name="writer",
                action="edit" if old is not None else "create",
                old_content=old,
                new_content=payload.get("content", "updated"),
            )
        return "ok"

    tool = _make_tool(name="writer", fn=impl)
    client = MockAnthropic()
    client.add_response_from_blocks(
        [
            tool_use_block(
                tool.name,
                {"path": str(target_file), "content": "updated"},
                tool_use_id="tool-1",
            )
        ]
    )
    client.add_response_from_blocks([text_block("done")])

    options = AgentRunOptions(changes_log_path=tmp_path / "changes.jsonl")
    runner = AgentRunner([tool], options, client=client)

    runner.run("Update file")
    assert target_file.read_text(encoding="utf-8") == "updated"

    operations = runner.undo_last_turn()
    assert target_file.read_text(encoding="utf-8") == "initial"
    assert operations

    log_entries = (tmp_path / "changes.jsonl").read_text(encoding="utf-8").strip().splitlines()
    undo_entry = json.loads(log_entries[-1])
    assert undo_entry.get("undo") is True
    assert "tracked.txt" in "\n".join(undo_entry.get("operations", []))


def test_agent_runner_handles_fatal_tool_error(tmp_path):
    def impl(_payload):
        raise FatalToolError("boom")

    tool = _make_tool(fn=impl)
    client = MockAnthropic()
    client.add_response_from_blocks(
        [tool_use_block(tool.name, {"path": "notes.txt"}, tool_use_id="tool-1")]
    )
    client.add_response_from_blocks([text_block("should not reach")])

    options = AgentRunOptions()
    runner = AgentRunner([tool], options, client=client)

    result = runner.run("Do something")

    assert result.stopped_reason == "fatal_tool_error"
    assert result.turns_used == 1
    assert result.tool_events and result.tool_events[0].metadata.get("error_type") == "fatal"


def test_agent_runner_blocks_disallowed_tools():
    tool = _make_tool()
    client = MockAnthropic()
    client.add_response_from_blocks(
        [tool_use_block(tool.name, {"path": "notes.txt"}, tool_use_id="tool-1")]
    )
    client.add_response_from_blocks([text_block("fallback answer")])

    options = AgentRunOptions(blocked_tools={tool.name})
    runner = AgentRunner([tool], options, client=client)

    result = runner.run("Prompt")

    assert runner.active_tools == []
    assert len(result.tool_events) == 1
    event = result.tool_events[0]
    assert event.is_error is True
    assert event.skipped is False
    assert "not permitted" in event.result
    assert result.edited_files == []


def test_agent_runner_dry_run_skips_execution():
    executed = []

    def impl(payload):  # pragma: no cover - should not run
        executed.append(payload["path"])
        return "ok"

    tool = _make_tool(fn=impl)
    client = MockAnthropic()
    client.add_response_from_blocks(
        [tool_use_block(tool.name, {"path": "draft.txt"}, tool_use_id="tool-1")]
    )
    client.add_response_from_blocks([text_block("summary")])

    options = AgentRunOptions(dry_run=True)
    runner = AgentRunner([tool], options, client=client)

    result = runner.run("Prompt")

    assert executed == []
    assert len(result.tool_events) == 1
    event = result.tool_events[0]
    assert event.skipped is True
    assert event.is_error is True
    assert "dry-run" in event.result
    assert result.edited_files == ["draft.txt"]


def test_agent_runner_tool_debug_logging(tmp_path, capsys):
    tool = _make_tool(name="logger", capabilities={"write_fs"})
    client = MockAnthropic()
    client.add_response_from_blocks(
        [tool_use_block(tool.name, {"path": "notes.txt"}, tool_use_id="tool-1")]
    )
    client.add_response_from_blocks([text_block("done")])

    debug_path = tmp_path / "tool-debug.jsonl"
    options = AgentRunOptions(debug_tool_use=True, tool_debug_log_path=debug_path)
    runner = AgentRunner([tool], options, client=client)

    runner.run("Prompt")

    captured = capsys.readouterr()
    assert "[tool-debug]" in captured.err

    contents = debug_path.read_text(encoding="utf-8").strip().splitlines()
    assert contents
    payload = json.loads(contents[0])
    assert payload["tool"] == tool.name
    assert payload["input"]["path"] == "notes.txt"
    assert payload["is_error"] is False



class DummyMcpClient:
    def __init__(self):
        self.calls = 0

    async def list_tools(self):
        self.calls += 1
        from types import SimpleNamespace

        return SimpleNamespace(
            tools=[
                SimpleNamespace(
                    name="navigate",
                    description="Navigate page",
                    inputSchema={"type": "object", "properties": {}},
                )
            ]
        )


class DummyContext:
    def __init__(self, client):
        self._client = client
        self.telemetry = type("T", (), {"incr": staticmethod(lambda *_: None)})()

    async def get_mcp_client(self, name: str):
        return self._client

    async def mark_mcp_client_unhealthy(self, name: str):
        self.marked = name


def test_agent_runner_discovers_mcp_tools():
    definition = MCPServerDefinition(
        name="chrome-devtools",
        command="npx",
        args=("-y", "chrome-devtools-mcp@latest"),
    )

    async def factory(server: str):  # pragma: no cover - simple stub
        return DummyMcpClient()

    runner = AgentRunner(
        tools=[],
        options=AgentRunOptions(),
        client=MockAnthropic(),
        session_settings=SessionSettings(mcp=MCPSettings(enable=True, definitions=(definition,))),
        mcp_client_factory=factory,
    )

    context = DummyContext(DummyMcpClient())

    async def _run():
        await runner._discover_mcp_tools(context)

    asyncio.run(_run())

    assert any(spec.spec.name == "chrome-devtools/navigate" for spec in runner._configured_specs)
    assert "chrome-devtools/navigate" in runner._registered_mcp_tools
