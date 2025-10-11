import json
from pathlib import Path

import pytest

import tools_todo_write
from tools_todo_write import todo_write_impl
from session.turn_diff_tracker import TurnDiffTracker


def _set_store(tmp_path: Path, monkeypatch):
    store_path = tmp_path / "todos.json"
    monkeypatch.setattr(tools_todo_write, "_STORE_PATH", store_path)
    return store_path


def test_replace_todos(tmp_path: Path, monkeypatch):
    _set_store(tmp_path, monkeypatch)
    result = json.loads(
        todo_write_impl(
            {
                "merge": False,
                "todos": [
                    {"id": "build", "content": "Run build", "status": "pending"},
                    {"id": "test", "content": "Run tests", "status": "in_progress"},
                ],
            }
        )
    )
    assert len(result["todos"]) == 2
    assert result["todos"][0]["id"] == "build"


def test_merge_updates_existing(tmp_path: Path, monkeypatch):
    store_path = _set_store(tmp_path, monkeypatch)
    store_path.write_text(
        json.dumps({
            "todos": [
                {"id": "build", "content": "Run build", "status": "pending"},
            ],
            "updated_at": None,
        })
    )

    result = json.loads(
        todo_write_impl(
            {
                "merge": True,
                "todos": [
                    {"id": "build", "status": "completed"},
                    {"id": "deploy", "content": "Deploy to staging"},
                ],
            }
        )
    )

    todos = {item["id"]: item for item in result["todos"]}
    assert todos["build"]["status"] == "completed"
    assert todos["deploy"]["content"] == "Deploy to staging"


def test_invalid_status_raises(tmp_path: Path, monkeypatch):
    _set_store(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        todo_write_impl(
            {
                "merge": False,
                "todos": [
                    {"id": "one", "status": "blocked"},
                ],
            }
        )


def test_todo_write_records_tracker(tmp_path: Path, monkeypatch):
    store_path = _set_store(tmp_path, monkeypatch)
    tracker = TurnDiffTracker(turn_id=13)

    todo_write_impl(
        {
            "merge": False,
            "todos": [
                {"id": "one", "content": "First task"},
            ],
        },
        tracker=tracker,
    )

    edits = tracker.get_edits_for_path(store_path)
    assert edits
    assert edits[-1].tool_name == "todo_write"
    assert edits[-1].new_content is not None and "First task" in edits[-1].new_content
