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
