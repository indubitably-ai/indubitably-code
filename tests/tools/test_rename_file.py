import json
from pathlib import Path

import pytest

from tools_rename_file import rename_file_impl
from session.turn_diff_tracker import TurnDiffTracker


def test_rename_file(tmp_path: Path):
    src = tmp_path / "src.txt"
    dest = tmp_path / "dest.txt"
    src.write_text("data", encoding="utf-8")
    result = json.loads(
        rename_file_impl({
            "source_path": str(src),
            "dest_path": str(dest),
        })
    )
    assert result["ok"] is True
    assert dest.exists()
    assert dest.read_text(encoding="utf-8") == "data"


def test_rename_file_overwrite(tmp_path: Path):
    src = tmp_path / "src.txt"
    dest = tmp_path / "dest.txt"
    src.write_text("data", encoding="utf-8")
    dest.write_text("old", encoding="utf-8")
    result = json.loads(
        rename_file_impl({
            "source_path": str(src),
            "dest_path": str(dest),
            "overwrite": True,
        })
    )
    assert result["overwritten"] is True
    assert dest.read_text(encoding="utf-8") == "data"


def test_rename_file_identical_paths(tmp_path: Path):
    src = tmp_path / "file.txt"
    src.write_text("data", encoding="utf-8")
    with pytest.raises(ValueError):
        rename_file_impl({
            "source_path": str(src),
            "dest_path": str(src),
        })


def test_rename_file_records_tracker(tmp_path: Path) -> None:
    src = tmp_path / "source.txt"
    dest = tmp_path / "dest.txt"
    src.write_text("data", encoding="utf-8")
    tracker = TurnDiffTracker(turn_id=12)

    rename_file_impl(
        {
            "source_path": str(src),
            "dest_path": str(dest),
        },
        tracker=tracker,
    )

    edits = tracker.get_edits_for_path(src)
    assert edits
    assert edits[-1].action == "rename"
    assert edits[-1].new_content == str(dest)
