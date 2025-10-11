import json
from pathlib import Path

import pytest

from tools_line_edit import line_edit_impl
from session.turn_diff_tracker import TurnDiffTracker


@pytest.fixture
def sample(tmp_path: Path) -> Path:
    path = tmp_path / "doc.txt"
    path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    return path


def test_line_edit_insert_before(sample: Path):
    result = json.loads(
        line_edit_impl({
            "path": str(sample),
            "mode": "insert_before",
            "line": 2,
            "text": "inserted\n",
        })
    )
    assert result["action"] == "insert_before"
    assert "inserted\n" in sample.read_text(encoding="utf-8")


def test_line_edit_replace_anchor(sample: Path):
    result = json.loads(
        line_edit_impl({
            "path": str(sample),
            "mode": "replace",
            "anchor": "beta",
            "text": "beta2\n",
        })
    )
    assert result["lines_changed"] == 1
    assert "beta2" in sample.read_text(encoding="utf-8")


def test_line_edit_delete_lines(sample: Path):
    result = json.loads(
        line_edit_impl({
            "path": str(sample),
            "mode": "delete",
            "line": 2,
            "line_count": 1,
        })
    )
    assert result["action"] == "delete"
    contents = sample.read_text(encoding="utf-8")
    assert "beta" not in contents


def test_line_edit_invalid_position(sample: Path):
    with pytest.raises(ValueError):
        line_edit_impl({
            "path": str(sample),
            "mode": "replace",
            "text": "x\n",
        })


def test_line_edit_records_tracker(sample: Path) -> None:
    tracker = TurnDiffTracker(turn_id=6)

    line_edit_impl(
        {
            "path": str(sample),
            "mode": "replace",
            "line": 2,
            "line_count": 1,
            "text": "beta2\n",
        },
        tracker=tracker,
    )

    edits = tracker.get_edits_for_path(sample)
    assert edits
    assert edits[0].tool_name == "line_edit"
    assert edits[-1].new_content is not None and "beta2" in edits[-1].new_content
