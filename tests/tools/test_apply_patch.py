import asyncio
import json
from pathlib import Path
from typing import Tuple

import pytest

from agent import Tool
from tools.handlers.function import FunctionToolHandler
from tools_apply_patch import apply_patch_impl
from tools.schemas import ApplyPatchInput
from session.turn_diff_tracker import TurnDiffTracker
from tests.tool_harness import MockToolContext, ToolTestHarness


def _make_tool() -> Tool:
    return Tool(
        name="apply_patch",
        description="",
        input_schema={"type": "object"},
        fn=apply_patch_impl,
    )


def _harness(tmp_path: Path) -> Tuple[ToolTestHarness, Path]:
    base = tmp_path / "repo"
    base.mkdir()
    context = MockToolContext.create(cwd=base)
    handler = FunctionToolHandler(_make_tool())
    return ToolTestHarness(handler, context=context), base


def _invoke(harness: ToolTestHarness, payload: dict[str, object]) -> dict[str, object]:
    result = asyncio.run(harness.invoke("apply_patch", payload))
    return json.loads(result.content)


def test_apply_patch_add(tmp_path: Path):
    harness, base = _harness(tmp_path)
    patch = """*** Add File: sample.txt
@@ -0,0 +1,2 @@
+hello
+world
"""
    result = _invoke(
        harness,
        {"file_path": str(base / "sample.txt"), "patch": patch},
    )
    assert result["ok"] is True
    assert (base / "sample.txt").read_text(encoding="utf-8") == "hello\nworld\n"


def test_apply_patch_dry_run_update(tmp_path: Path):
    harness, base = _harness(tmp_path)
    path = base / "sample.txt"
    path.write_text("hello\n", encoding="utf-8")
    patch = """*** Update File: sample.txt
@@ -1,1 +1,1 @@
-hello
+goodbye
"""
    result = _invoke(
        harness,
        {
            "file_path": str(path),
            "patch": patch,
            "dry_run": True,
        },
    )
    assert result["dry_run"] is True
    assert path.read_text(encoding="utf-8") == "hello\n"


def test_apply_patch_header_mismatch(tmp_path: Path):
    harness, base = _harness(tmp_path)
    path = base / "sample.txt"
    path.write_text("hello\n", encoding="utf-8")
    patch = """*** Update File: other.txt
@@ -1,1 +1,1 @@
-hello
+hi
"""
    result = _invoke(
        harness,
        {"file_path": str(path), "patch": patch},
    )
    assert result["ok"] is False
    assert "does not match" in result["error"]


def test_apply_patch_records_tracker(tmp_path: Path) -> None:
    path = tmp_path / "tracked.txt"
    path.write_text("hello\n", encoding="utf-8")
    patch = """*** Update File: tracked.txt
@@ -1,1 +1,1 @@
-hello
+goodbye
"""
    tracker = TurnDiffTracker(turn_id=9)

    apply_patch_impl(ApplyPatchInput(file_path=str(path), patch=patch), tracker=tracker)

    edits = tracker.get_edits_for_path(path)
    assert edits
    last_edit = edits[-1]
    assert last_edit.action in {"update", "add"}
    assert last_edit.new_content is not None and "goodbye" in last_edit.new_content
