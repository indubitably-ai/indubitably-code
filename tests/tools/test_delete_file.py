import asyncio
import json
from pathlib import Path

from agent import Tool
from tools.handlers.function import FunctionToolHandler
from tools_delete_file import delete_file_impl
from session.turn_diff_tracker import TurnDiffTracker
from tests.tool_harness import MockToolContext, ToolTestHarness


def _make_tool() -> Tool:
    return Tool(
        name="delete_file",
        description="",
        input_schema={"type": "object"},
        fn=delete_file_impl,
    )


def _harness(tmp_path: Path) -> tuple[ToolTestHarness, Path]:
    base = tmp_path / "repo"
    base.mkdir()
    context = MockToolContext.create(cwd=base)
    handler = FunctionToolHandler(_make_tool())
    return ToolTestHarness(handler, context=context), base


def _invoke(harness: ToolTestHarness, payload: dict[str, object]) -> dict[str, object]:
    result = asyncio.run(harness.invoke("delete_file", payload))
    return json.loads(result.content)


def test_delete_existing_file(tmp_path: Path):
    harness, base = _harness(tmp_path)
    path = base / "file.txt"
    path.write_text("data", encoding="utf-8")
    result = _invoke(harness, {"path": str(path)})
    assert result["ok"] is True
    assert not path.exists()


def test_delete_missing_file(tmp_path: Path):
    harness, base = _harness(tmp_path)
    path = base / "missing.txt"
    result = _invoke(harness, {"path": str(path)})
    assert result["ok"] is True
    assert "note" in result


def test_delete_directory_returns_error(tmp_path: Path):
    harness, base = _harness(tmp_path)
    path = base / "dir"
    path.mkdir()
    result = _invoke(harness, {"path": str(path)})
    assert result["ok"] is False
    assert result["error"] == "path is a directory"


def test_delete_file_records_tracker(tmp_path: Path) -> None:
    path = tmp_path / "tracked.txt"
    path.write_text("data", encoding="utf-8")
    tracker = TurnDiffTracker(turn_id=2)

    delete_file_impl({"path": str(path)}, tracker=tracker)

    edits = tracker.get_edits_for_path(path)
    assert len(edits) == 1
    assert edits[0].action == "delete"
    assert edits[0].old_content is not None and "data" in edits[0].old_content
