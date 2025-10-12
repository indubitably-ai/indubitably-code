import asyncio
import json
from pathlib import Path
from typing import Tuple

import pytest

from agent import Tool
from tools.handlers.function import FunctionToolHandler
from tools_line_edit import line_edit_impl
from session.turn_diff_tracker import TurnDiffTracker
from tests.tool_harness import MockToolContext, ToolTestHarness


def _make_tool() -> Tool:
    return Tool(
        name="line_edit",
        description="",
        input_schema={"type": "object"},
        fn=line_edit_impl,
    )


def _harness(tmp_path: Path) -> Tuple[ToolTestHarness, Path]:
    base = tmp_path / "repo"
    base.mkdir()
    context = MockToolContext.create(cwd=base)
    handler = FunctionToolHandler(_make_tool())
    return ToolTestHarness(handler, context=context), base


def _invoke(harness: ToolTestHarness, payload: dict[str, object]) -> dict[str, object]:
    result = asyncio.run(harness.invoke("line_edit", payload))
    return json.loads(result.content)


@pytest.fixture
def sample(tmp_path: Path) -> Tuple[ToolTestHarness, Path]:
    harness, base = _harness(tmp_path)
    path = base / "doc.txt"
    path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    return harness, path


def test_line_edit_insert_before(sample: Tuple[ToolTestHarness, Path]):
    harness, path = sample
    result = _invoke(
        harness,
        {
            "path": str(path),
            "mode": "insert_before",
            "line": 2,
            "text": "inserted\n",
        },
    )
    assert result["action"] == "insert_before"
    assert "inserted\n" in path.read_text(encoding="utf-8")


def test_line_edit_replace_anchor(sample: Tuple[ToolTestHarness, Path]):
    harness, path = sample
    result = _invoke(
        harness,
        {
            "path": str(path),
            "mode": "replace",
            "anchor": "beta",
            "text": "beta2\n",
        },
    )
    assert result["lines_changed"] == 1
    assert "beta2" in path.read_text(encoding="utf-8")


def test_line_edit_delete_lines(sample: Tuple[ToolTestHarness, Path]):
    harness, path = sample
    result = _invoke(
        harness,
        {
            "path": str(path),
            "mode": "delete",
            "line": 2,
            "line_count": 1,
        },
    )
    assert result["action"] == "delete"
    contents = path.read_text(encoding="utf-8")
    assert "beta" not in contents


def test_line_edit_invalid_position(sample: Tuple[ToolTestHarness, Path]):
    harness, path = sample
    with pytest.raises(ValueError):
        _invoke(
            harness,
            {
                "path": str(path),
                "mode": "replace",
                "text": "x\n",
            },
        )


def test_line_edit_records_tracker(sample: Tuple[ToolTestHarness, Path]) -> None:
    _harness_obj, path = sample
    tracker = TurnDiffTracker(turn_id=6)

    line_edit_impl(
        {
            "path": str(path),
            "mode": "replace",
            "line": 2,
            "line_count": 1,
            "text": "beta2\n",
        },
        tracker=tracker,
    )

    edits = tracker.get_edits_for_path(path)
    assert edits
    assert edits[0].tool_name == "line_edit"
    assert edits[-1].new_content is not None and "beta2" in edits[-1].new_content
