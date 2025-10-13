from pathlib import Path

import pytest

from session.turn_diff_tracker import FileEdit, TurnDiffTracker


def test_turn_diff_tracker_records_and_summarizes(tmp_path: Path) -> None:
    tracker = TurnDiffTracker(turn_id=7)
    file_path = tmp_path / "example.txt"

    tracker.record_edit(
        path=file_path,
        tool_name="test_tool",
        action="create",
        old_content=None,
        new_content="hello world\n",
    )

    summary = tracker.generate_summary()
    assert "Turn 7" in summary
    assert str(file_path.resolve()) in summary

    diff = tracker.generate_unified_diff()
    assert diff is None  # missing old content prevents diff

    tracker.record_edit(
        path=file_path,
        tool_name="test_tool",
        action="edit",
        old_content="hello world\n",
        new_content="hello python\n",
    )

    diff = tracker.generate_unified_diff()
    assert diff is not None
    assert "hello world" in diff
    assert "hello python" in diff


def test_turn_diff_tracker_locking(tmp_path: Path) -> None:
    tracker = TurnDiffTracker(turn_id=1)
    path = tmp_path / "file.txt"

    tracker.lock_file(path)
    with pytest.raises(ValueError):
        tracker.lock_file(path)
    tracker.unlock_file(path)

    tracker.record_edit(path=path, tool_name="tool", action="noop")
    edits = tracker.get_edits_for_path(path)
    assert len(edits) == 1
    assert isinstance(edits[0], FileEdit)


def test_turn_diff_tracker_detects_conflicts(tmp_path: Path) -> None:
    tracker = TurnDiffTracker(turn_id=2)
    path = tmp_path / "conflict.txt"

    tracker.record_edit(
        path=path,
        tool_name="tool_a",
        action="create",
        old_content=None,
        new_content="v1",
    )

    tracker.record_edit(
        path=path,
        tool_name="tool_b",
        action="edit",
        old_content="v1",
        new_content="v2",
    )

    tracker.record_edit(
        path=path,
        tool_name="tool_c",
        action="edit",
        old_content="external-change",
        new_content="v3",
    )

    assert tracker.conflicts
    report = tracker.generate_conflict_report()
    assert report and "conflict" in report.lower()


def test_turn_diff_tracker_undo(tmp_path: Path) -> None:
    tracker = TurnDiffTracker(turn_id=3)
    path = tmp_path / "file.txt"
    renamed_path = tmp_path / "renamed.txt"

    tracker.record_edit(
        path=path,
        tool_name="tool",
        action="create",
        old_content=None,
        new_content="alpha",
    )
    path.write_text("alpha", encoding="utf-8")

    tracker.record_edit(
        path=path,
        tool_name="tool",
        action="replace",
        old_content="alpha",
        new_content="beta",
    )
    path.write_text("beta", encoding="utf-8")

    path.rename(renamed_path)
    tracker.record_edit(
        path=path,
        tool_name="tool",
        action="rename",
        old_content=str(path.resolve()),
        new_content=str(renamed_path.resolve()),
    )

    ops = tracker.undo()
    assert ops
    assert not renamed_path.exists()
    assert not path.exists()
