import json

import textwrap

from typing import List, Optional

import pytest

import cli
from agent_runner import AgentRunResult, ToolEvent


class DummyRunner:
    instances = []
    next_planned_result: Optional[AgentRunResult] = None
    next_planned_undo: Optional[List[str]] = None

    def __init__(self, tools, options, session_settings=None):
        self.active_tools = tools
        self.options = options
        self.session_settings = session_settings
        self.called_with = None
        self.planned_result = DummyRunner.next_planned_result
        DummyRunner.next_planned_result = None
        self.planned_undo = DummyRunner.next_planned_undo
        DummyRunner.next_planned_undo = None
        self.undo_calls: List[List[str]] = []
        DummyRunner.instances.append(self)

    def run(self, prompt):
        self.called_with = prompt
        if self.planned_result is not None:
            return self.planned_result
        event = ToolEvent(
            turn=1,
            tool_name="edit_file",
            raw_input={"path": "file.txt"},
            result="ok",
            is_error=False,
            skipped=False,
            paths=["file.txt"],
        )
        return AgentRunResult(
            final_response="done",
            tool_events=[event],
            edited_files=["file.txt"],
            turns_used=2,
            stopped_reason="completed",
            conversation=[],
            turn_summaries=[{"turn": 1, "summary": "Turn 1 modifications:", "paths": ["file.txt"]}],
        )

    def undo_last_turn(self):
        operations = self.planned_undo or ["reverted file.txt"]
        self.undo_calls.append(list(operations))
        return operations


@pytest.fixture(autouse=True)
def _patch_runner(monkeypatch):
    DummyRunner.instances = []
    DummyRunner.next_planned_result = None
    DummyRunner.next_planned_undo = None
    monkeypatch.setattr(cli, "AgentRunner", DummyRunner)
    monkeypatch.setattr(cli, "build_default_tools", lambda: [])
    yield


def test_cli_json_output(capsys):
    exit_code = cli.main(["--prompt", "Summarize repo", "--json"])

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["final_response"] == "done"
    assert payload["edited_files"] == ["file.txt"]
    assert payload["turn_summaries"][0]["paths"] == ["file.txt"]
    assert "undo_operations" not in payload
    assert DummyRunner.instances[-1].options.max_turns == 8


def test_cli_human_output(capsys):
    exit_code = cli.main(["--prompt", "Hi there"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "done" in captured.out
    assert "Tools executed" in captured.out
    assert "file.txt" in captured.out
    assert "Turn change summaries" in captured.out


def test_cli_undo_flag_triggers_undo(capsys):
    exit_code = cli.main(["--prompt", "Hi there", "--undo-last-turn"])

    assert exit_code == 0
    runner = DummyRunner.instances[-1]
    assert runner.undo_calls
    captured = capsys.readouterr()
    assert "Undo operations" in captured.out


def test_cli_json_undo_output(capsys):
    exit_code = cli.main(["--prompt", "Summarize", "--json", "--undo-last-turn"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["undo_operations"]
    runner = DummyRunner.instances[-1]
    assert runner.undo_calls


def test_cli_uses_config_file(tmp_path, capsys):
    config_path = tmp_path / "agent.toml"
    config_path.write_text(
        textwrap.dedent(
            """
            [runner]
            max_turns = 5
            exit_on_tool_error = true
            allowed_tools = ["read_file"]
            blocked_tools = ["edit_file"]
            audit_log = "logs/audit.jsonl"
            changes_log = "changes.jsonl"
            """
        ),
        encoding="utf-8",
    )

    exit_code = cli.main(["--config", str(config_path), "--prompt", "Hello"])

    assert exit_code == 0
    runner = DummyRunner.instances[-1]
    assert runner.options.max_turns == 5
    assert runner.options.exit_on_tool_error is True
    assert runner.options.allowed_tools == {"read_file"}
    assert runner.options.blocked_tools == {"edit_file"}
    assert str(runner.options.audit_log_path).endswith("logs/audit.jsonl")
    assert str(runner.options.changes_log_path).endswith("changes.jsonl")


def test_cli_arguments_override_config(tmp_path):
    config_path = tmp_path / "agent.toml"
    config_path.write_text(
        textwrap.dedent(
            """
            [runner]
            max_turns = 2
            dry_run = true
            """
        ),
        encoding="utf-8",
    )

    exit_code = cli.main([
        "--config",
        str(config_path),
        "--prompt",
        "Hi",
        "--max-turns",
        "9",
        "--no-dry-run",
    ])

    assert exit_code == 0
    runner = DummyRunner.instances[-1]
    assert runner.options.max_turns == 9
    assert runner.options.dry_run is False


def test_cli_reports_fatal_error(capsys):
    fatal_event = ToolEvent(
        turn=1,
        tool_name="danger",
        raw_input={},
        result="fatal boom",
        is_error=True,
        skipped=False,
        paths=[],
        metadata={"error_type": "fatal"},
    )
    DummyRunner.next_planned_result = AgentRunResult(
        final_response="",
        tool_events=[fatal_event],
        edited_files=[],
        turns_used=1,
        stopped_reason="fatal_tool_error",
        conversation=[],
        turn_summaries=[],
    )

    exit_code = cli.main(["--prompt", "fatal please"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Fatal tool error" in captured.err
