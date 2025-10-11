import json
from pathlib import Path

from tools_delete_file import delete_file_impl
from session.turn_diff_tracker import TurnDiffTracker


def test_delete_existing_file(tmp_path: Path):
    path = tmp_path / "file.txt"
    path.write_text("data", encoding="utf-8")
    result = json.loads(delete_file_impl({"path": str(path)}))
    assert result["ok"] is True
    assert not path.exists()


def test_delete_missing_file(tmp_path: Path):
    path = tmp_path / "missing.txt"
    result = json.loads(delete_file_impl({"path": str(path)}))
    assert result["ok"] is True
    assert "note" in result


def test_delete_directory_returns_error(tmp_path: Path):
    path = tmp_path / "dir"
    path.mkdir()
    result = json.loads(delete_file_impl({"path": str(path)}))
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
