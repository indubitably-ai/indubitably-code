import json
from pathlib import Path

import pytest
from session.turn_diff_tracker import TurnDiffTracker
from tools.schemas import TodoWriteInput
from tools_todo_write import todo_write_impl


def _set_store(base: Path, monkeypatch) -> Path:
    store = base / ".session_todos.json"
    monkeypatch.chdir(base)
    if store.exists():
        store.unlink()
    return store


def _invoke(payload: dict) -> dict:
    out = todo_write_impl(TodoWriteInput(**payload))
    return json.loads(out.content)


def test_replace_todos(tmp_path: Path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    _set_store(base, monkeypatch)
    result = _invoke(
        {
            "merge": False,
            "todos": [
                {"id": "build", "content": "Run build", "status": "pending"},
                {"id": "test", "content": "Run tests", "status": "in_progress"},
            ],
        },
    )
    assert result["todos"][0]["id"] == "build"


def test_merge_updates_existing(tmp_path: Path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    store_path = _set_store(base, monkeypatch)
    store_path.write_text(
        json.dumps(
            {
                "todos": [
                    {"id": "build", "content": "Run build", "status": "pending"},
                ],
                "updated_at": None,
            }
        )
    )

    result = _invoke(
        {
            "merge": True,
            "todos": [
                {"id": "build", "status": "completed"},
                {"id": "deploy", "content": "Deploy to staging"},
            ],
        },
    )

    ids = [t["id"] for t in result["todos"]]
    assert "build" in ids and "deploy" in ids


def test_invalid_status_raises(tmp_path: Path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    _set_store(base, monkeypatch)
    with pytest.raises(ValueError):
        _invoke(
            {
                "merge": False,
                "todos": [
                    {"id": "one", "status": "blocked"},
                ],
            },
        )


def test_todo_write_records_tracker(tmp_path: Path, monkeypatch):
    base = tmp_path / "repo"
    base.mkdir()
    _set_store(base, monkeypatch)
    tracker = TurnDiffTracker(turn_id=13)

    todo_write_impl(
        TodoWriteInput(**{
            "merge": False,
            "todos": [
                {"id": "one", "content": "First task"},
            ],
        }),
        tracker=tracker,
    )

    store_path = base / ".session_todos.json"
    edits = tracker.get_edits_for_path(store_path)
    assert edits
    assert edits[-1].tool_name == "todo_write"
    assert edits[-1].new_content is not None and "First task" in edits[-1].new_content
