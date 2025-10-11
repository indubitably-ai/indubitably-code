import json
from pathlib import Path

import pytest

from tools_create_file import create_file_impl
from session.turn_diff_tracker import TurnDiffTracker


def test_create_file_creates_new(tmp_path: Path):
    path = tmp_path / "new.txt"
    result = json.loads(
        create_file_impl({
            "path": str(path),
            "content": "hello",
        })
    )
    assert result["action"] == "create"
    assert path.read_text(encoding="utf-8") == "hello"


def test_create_file_overwrite(tmp_path: Path):
    path = tmp_path / "file.txt"
    path.write_text("old", encoding="utf-8")
    result = json.loads(
        create_file_impl({
            "path": str(path),
            "content": "new",
            "if_exists": "overwrite",
        })
    )
    assert result["action"] == "overwrite"
    assert path.read_text(encoding="utf-8") == "new"


def test_create_file_skip(tmp_path: Path):
    path = tmp_path / "file.txt"
    path.write_text("data", encoding="utf-8")
    result = json.loads(
        create_file_impl({
            "path": str(path),
            "content": "ignored",
            "if_exists": "skip",
        })
    )
    assert result["action"] == "skip"
    assert path.read_text(encoding="utf-8") == "data"


def test_create_file_missing_parent(tmp_path: Path):
    path = tmp_path / "missing" / "file.txt"
    with pytest.raises(FileNotFoundError):
        create_file_impl({
            "path": str(path),
            "create_parents": False,
        })


def test_create_file_invalid_policy(tmp_path: Path):
    with pytest.raises(ValueError):
        create_file_impl({
            "path": str(tmp_path / "x.txt"),
            "if_exists": "invalid",
        })


def test_create_file_records_tracker(tmp_path: Path) -> None:
    path = tmp_path / "tracked.txt"
    tracker = TurnDiffTracker(turn_id=5)

    create_file_impl({"path": str(path), "content": "hello"}, tracker=tracker)

    edits = tracker.get_edits_for_path(path)
    assert len(edits) == 1
    assert edits[0].action == "create"
    assert edits[0].new_content == "hello"
