import json
from pathlib import Path

import pytest

from tools_apply_patch import apply_patch_impl
from session.turn_diff_tracker import TurnDiffTracker


def test_apply_patch_add(tmp_path: Path):
    patch = """*** Add File: sample.txt
@@ -0,0 +1,2 @@
+hello
+world
"""
    result = json.loads(
        apply_patch_impl({"file_path": str(tmp_path / "sample.txt"), "patch": patch})
    )
    assert result["ok"] is True
    assert (tmp_path / "sample.txt").read_text(encoding="utf-8") == "hello\nworld\n"


def test_apply_patch_dry_run_update(tmp_path: Path):
    path = tmp_path / "sample.txt"
    path.write_text("hello\n", encoding="utf-8")
    patch = """*** Update File: sample.txt
@@ -1,1 +1,1 @@
-hello
+goodbye
"""
    result = json.loads(
        apply_patch_impl({
            "file_path": str(path),
            "patch": patch,
            "dry_run": True,
        })
    )
    assert result["dry_run"] is True
    assert path.read_text(encoding="utf-8") == "hello\n"


def test_apply_patch_header_mismatch(tmp_path: Path):
    path = tmp_path / "sample.txt"
    path.write_text("hello\n", encoding="utf-8")
    patch = """*** Update File: other.txt
@@ -1,1 +1,1 @@
-hello
+hi
"""
    result = json.loads(
        apply_patch_impl({"file_path": str(path), "patch": patch})
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

    apply_patch_impl({"file_path": str(path), "patch": patch}, tracker=tracker)

    edits = tracker.get_edits_for_path(path)
    assert edits
    last_edit = edits[-1]
    assert last_edit.action in {"update", "add"}
    assert last_edit.new_content is not None and "goodbye" in last_edit.new_content
