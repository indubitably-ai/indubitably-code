import asyncio
import json
from pathlib import Path
from typing import Tuple

import pytest

from agent import Tool
from tools.handlers.function import FunctionToolHandler
from tools_template_block import template_block_impl
from session.turn_diff_tracker import TurnDiffTracker
from tests.tool_harness import MockToolContext, ToolTestHarness


def _make_tool() -> Tool:
    return Tool(
        name="template_block",
        description="",
        input_schema={"type": "object"},
        fn=template_block_impl,
    )


def _harness(tmp_path: Path) -> Tuple[ToolTestHarness, Path]:
    base = tmp_path / "repo"
    base.mkdir()
    context = MockToolContext.create(cwd=base)
    handler = FunctionToolHandler(_make_tool())
    return ToolTestHarness(handler, context=context), base


def _invoke(harness: ToolTestHarness, payload: dict[str, object]) -> dict[str, object]:
    result = asyncio.run(harness.invoke("template_block", payload))
    return json.loads(result.content)


def test_template_insert_before(tmp_path: Path):
    harness, base = _harness(tmp_path)
    path = base / "file.txt"
    path.write_text("alpha\nbeta\n", encoding="utf-8")
    result = _invoke(
        harness,
        {
            "path": str(path),
            "mode": "insert_before",
            "anchor": "beta\n",
            "template": "inserted\n",
        },
    )
    assert result["action"] == "insert_before"
    assert "inserted" in path.read_text(encoding="utf-8")


def test_template_replace_with_expected(tmp_path: Path):
    harness, base = _harness(tmp_path)
    path = base / "file.txt"
    path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    result = _invoke(
        harness,
        {
            "path": str(path),
            "mode": "replace_block",
            "anchor": "beta\n",
            "template": "beta2\n",
            "expected_block": "beta\n",
        },
    )
    assert result["action"] == "replace_block"
    assert "beta2" in path.read_text(encoding="utf-8")


def test_template_replace_mismatch_returns_error(tmp_path: Path):
    harness, base = _harness(tmp_path)
    path = base / "file.txt"
    path.write_text("alpha\nbeta\n", encoding="utf-8")
    result = _invoke(
        harness,
        {
            "path": str(path),
            "mode": "replace_block",
            "anchor": "beta\n",
            "template": "beta2\n",
            "expected_block": "something else\n",
        },
    )
    assert result["ok"] is False
    assert "expected_block" in result["error"]


def test_template_missing_anchor(tmp_path: Path):
    harness, base = _harness(tmp_path)
    path = base / "file.txt"
    path.write_text("alpha\n", encoding="utf-8")
    result = _invoke(
        harness,
        {
            "path": str(path),
            "mode": "insert_before",
            "anchor": "beta\n",
            "template": "inserted\n",
        },
    )
    assert result["ok"] is False
    assert "anchor" in result["error"]


def test_template_block_records_tracker(tmp_path: Path) -> None:
    path = tmp_path / "file.txt"
    path.write_text("alpha\nbeta\n", encoding="utf-8")
    tracker = TurnDiffTracker(turn_id=11)

    template_block_impl(
        {
            "path": str(path),
            "mode": "insert_after",
            "anchor": "alpha\n",
            "template": "inserted\n",
        },
        tracker=tracker,
    )

    edits = tracker.get_edits_for_path(path)
    assert edits
    assert edits[-1].tool_name == "template_block"
    assert edits[-1].new_content is not None and "inserted" in edits[-1].new_content
