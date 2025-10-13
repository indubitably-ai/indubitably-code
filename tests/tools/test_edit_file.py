import json
from pathlib import Path

import pytest

from agent import Tool
from tools.handlers.function import FunctionToolHandler
from tools_edit import edit_file_impl
from tools.schemas import EditFileInput
from session.turn_diff_tracker import TurnDiffTracker
from tests.tool_harness import MockToolContext, ToolTestHarness


def _make_tool() -> Tool:
    return Tool(
        name="edit_file",
        description="",
        input_schema={"type": "object"},
        fn=edit_file_impl,
    )


def _harness(tmp_path: Path) -> tuple[ToolTestHarness, Path]:
    base = tmp_path / "repo"
    base.mkdir()
    context = MockToolContext.create(cwd=base)
    handler = FunctionToolHandler(_make_tool())
    return ToolTestHarness(handler, context=context), base


def test_edit_file_replaces_occurrence(tmp_path: Path):
    harness, base = _harness(tmp_path)
    path = base / "file.txt"
    path.write_text("hello world", encoding="utf-8")
    result = json.loads(
        edit_file_impl(EditFileInput(path=str(path), old_str="world", new_str="python")).content
    )
    assert result["ok"] is True
    assert path.read_text(encoding="utf-8") == "hello python"


def test_edit_file_dry_run_reports(tmp_path: Path):
    harness, base = _harness(tmp_path)
    path = base / "file.txt"
    path.write_text("foo foo", encoding="utf-8")
    result = json.loads(
        edit_file_impl(EditFileInput(path=str(path), old_str="foo", new_str="bar", dry_run=True)).content
    )
    assert result["dry_run"] is True
    assert result["replacements"] == 2
    assert path.read_text(encoding="utf-8") == "foo foo"


def test_edit_file_missing_old_returns_error(tmp_path: Path):
    harness, base = _harness(tmp_path)
    path = base / "file.txt"
    path.write_text("hello", encoding="utf-8")
    out = edit_file_impl(EditFileInput(path=str(path), old_str="absent", new_str="value"))
    assert out.success is False
    assert "absent" in out.content or "not found" in out.content.lower()


def test_edit_file_create_new(tmp_path: Path):
    harness, base = _harness(tmp_path)
    path = base / "new.txt"
    result = json.loads(
        edit_file_impl(EditFileInput(path=str(path), old_str="", new_str="content")).content
    )
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "content"
    assert result["action"] == "create"


def test_edit_file_records_turn_diff(tmp_path: Path) -> None:
    path = tmp_path / "tracked.txt"
    path.write_text("hello world", encoding="utf-8")
    tracker = TurnDiffTracker(turn_id=3)

    edit_file_impl(EditFileInput(path=str(path), old_str="world", new_str="python"), tracker=tracker)

    edits = tracker.get_edits_for_path(path)
    assert len(edits) == 1
    assert edits[0].action == "replace"
    assert edits[0].new_content is not None and "hello python" in edits[0].new_content
