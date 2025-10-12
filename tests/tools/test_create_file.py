import asyncio
import json
from pathlib import Path

import pytest

from agent import Tool
from tools.handlers.function import FunctionToolHandler
from tools_create_file import create_file_impl
from session.turn_diff_tracker import TurnDiffTracker
from tests.tool_harness import MockToolContext, ToolTestHarness


def _make_tool() -> Tool:
    return Tool(
        name="create_file",
        description="",
        input_schema={"type": "object"},
        fn=create_file_impl,
    )


def _harness(tmp_path: Path) -> tuple[ToolTestHarness, Path]:
    base = tmp_path / "repo"
    base.mkdir()
    context = MockToolContext.create(cwd=base)
    handler = FunctionToolHandler(_make_tool())
    return ToolTestHarness(handler, context=context), base


def _invoke(harness: ToolTestHarness, payload: dict[str, object]) -> dict[str, object]:
    result = asyncio.run(harness.invoke("create_file", payload))
    return json.loads(result.content)


def test_create_file_creates_new(tmp_path: Path):
    harness, base = _harness(tmp_path)
    path = base / "new.txt"
    result = _invoke(
        harness,
        {
            "path": str(path),
            "content": "hello",
        },
    )
    assert result["action"] == "create"
    assert path.read_text(encoding="utf-8") == "hello"


def test_create_file_overwrite(tmp_path: Path):
    harness, base = _harness(tmp_path)
    path = base / "file.txt"
    path.write_text("old", encoding="utf-8")
    result = _invoke(
        harness,
        {
            "path": str(path),
            "content": "new",
            "if_exists": "overwrite",
        },
    )
    assert result["action"] == "overwrite"
    assert path.read_text(encoding="utf-8") == "new"


def test_create_file_skip(tmp_path: Path):
    harness, base = _harness(tmp_path)
    path = base / "file.txt"
    path.write_text("data", encoding="utf-8")
    result = _invoke(
        harness,
        {
            "path": str(path),
            "content": "ignored",
            "if_exists": "skip",
        },
    )
    assert result["action"] == "skip"
    assert path.read_text(encoding="utf-8") == "data"


def test_create_file_missing_parent(tmp_path: Path):
    harness, base = _harness(tmp_path)
    path = base / "missing" / "file.txt"
    result = asyncio.run(
        harness.invoke(
            "create_file",
            {
                "path": str(path),
                "create_parents": False,
            },
        )
    )
    assert result.success is False
    assert "parent directory missing" in result.content


def test_create_file_invalid_policy(tmp_path: Path):
    harness, base = _harness(tmp_path)
    result = asyncio.run(
        harness.invoke(
            "create_file",
            {
                "path": str(base / "x.txt"),
                "if_exists": "invalid",
            },
        )
    )
    assert result.success is False
    assert "Value error" in result.content


def test_create_file_records_tracker(tmp_path: Path) -> None:
    path = tmp_path / "tracked.txt"
    tracker = TurnDiffTracker(turn_id=5)

    create_file_impl({"path": str(path), "content": "hello"}, tracker=tracker)

    edits = tracker.get_edits_for_path(path)
    assert len(edits) == 1
    assert edits[0].action == "create"
    assert edits[0].new_content == "hello"
