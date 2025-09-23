from types import SimpleNamespace

import json

import pytest

from agent import Tool
from agents_md import load_agents_md
from agent_runner import AgentRunOptions, AgentRunner


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


class SequencedClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0
        self.messages = self._Messages(self)

    class _Messages:
        def __init__(self, outer):
            self._outer = outer

        def create(self, **_):
            if not self._outer._responses:
                raise RuntimeError("no more responses configured")
            self._outer.calls += 1
            return SimpleNamespace(content=self._outer._responses.pop(0))


def test_agent_runner_executes_tools_and_tracks_files(tmp_path):
    executed = []

    def impl(payload):
        executed.append(payload["path"])
        return "ok"

    tool = _make_tool(fn=impl)
    responses = [
        [SimpleNamespace(type="tool_use", name=tool.name, input={"path": "notes.txt"}, id="tool-1")],
        [SimpleNamespace(type="text", text="all done")],
    ]
    client = SequencedClient(responses)

    options = AgentRunOptions(max_turns=3, audit_log_path=tmp_path / "audit.jsonl", changes_log_path=tmp_path / "changes.jsonl")
    runner = AgentRunner([tool], options, client=client)

    result = runner.run("Please update notes")

    assert result.final_response == "all done"
    assert executed == ["notes.txt"]
    assert result.edited_files == ["notes.txt"]
    assert len(result.tool_events) == 1
    assert result.tool_events[0].tool_name == tool.name

    audit = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert audit and json.loads(audit[0])["tool"] == tool.name

    changes = (tmp_path / "changes.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert changes and json.loads(changes[0])["path"] == "notes.txt"
    doc = load_agents_md()
    assert doc is not None
    assert result.conversation
    first_message = result.conversation[0]
    assert first_message["role"] == "system"
    assert first_message["content"]
    assert doc.system_text().splitlines()[0] in first_message["content"][0]["text"]


def test_agent_runner_blocks_disallowed_tools():
    tool = _make_tool()
    responses = [
        [SimpleNamespace(type="tool_use", name=tool.name, input={"path": "notes.txt"}, id="tool-1")],
        [SimpleNamespace(type="text", text="fallback answer")],
    ]
    client = SequencedClient(responses)

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
    responses = [
        [SimpleNamespace(type="tool_use", name=tool.name, input={"path": "draft.txt"}, id="tool-1")],
        [SimpleNamespace(type="text", text="summary")],
    ]
    client = SequencedClient(responses)

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
    responses = [
        [SimpleNamespace(type="tool_use", name=tool.name, input={"path": "notes.txt"}, id="tool-1")],
        [SimpleNamespace(type="text", text="done")],
    ]
    client = SequencedClient(responses)

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
