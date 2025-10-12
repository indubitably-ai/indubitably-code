import asyncio
import json
from pathlib import Path
from typing import Tuple

import pytest

import tools_todo_write
from agent import Tool
from tools.handlers.function import FunctionToolHandler
from tools_todo_write import todo_write_impl
from session.turn_diff_tracker import TurnDiffTracker
from tests.tool_harness import MockToolContext, ToolTestHarness


def _make_tool() -> Tool:
    return Tool(
        name="todo_write",
        description="",
        input_schema={"type": "object"},
        fn=todo_write_impl,
    )


def _harness(tmp_path: Path) -> Tuple[ToolTestHarness, Path]:
    base = tmp_path / "repo"
    base.mkdir()
    context = MockToolContext.create(cwd=base)
    handler = FunctionToolHandler(_make_tool())
    return ToolTestHarness(handler, context=context), base


def _set_store(base: Path, monkeypatch) -> Path:
    store_path = base / "todos.json"
    monkeypatch.setattr(tools_todo_write, "_STORE_PATH", store_path)
    return store_path


def _invoke(harness: ToolTestHarness, payload: dict[str, object]) -> dict[str, object]:
    result = asyncio.run(harness.invoke("todo_write", payload))
    return json.loads(result.content)


def test_replace_todos(tmp_path: Path, monkeypatch):
    harness, base = _harness(tmp_path)
    _set_store(base, monkeypatch)
    result = _invoke(
        harness,
        {
            "merge": False,
            "todos": [
                {"id": "build", "content": "Run build", "status": "pending"},
                {"id": "test", "content": "Run tests", "status": "in_progress"},
            ],
        },
    )
    assert len(result["todos"]) == 2
    assert result["todos"][0]["id"] == "build"


def test_merge_updates_existing(tmp_path: Path, monkeypatch):
    harness, base = _harness(tmp_path)
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
        harness,
        {
            "merge": True,
            "todos": [
                {"id": "build", "status": "completed"},
                {"id": "deploy", "content": "Deploy to staging"},
            ],
        },
    )

    todos = {item["id"]: item for item in result["todos"]}
    assert todos["build"]["status"] == "completed"
    assert todos["deploy"]["content"] == "Deploy to staging"


def test_invalid_status_raises(tmp_path: Path, monkeypatch):
    harness, base = _harness(tmp_path)
    _set_store(base, monkeypatch)
    with pytest.raises(ValueError):
        _invoke(
            harness,
            {
                "merge": False,
                "todos": [
                    {"id": "one", "status": "blocked"},
                ],
            },
        )


def test_todo_write_records_tracker(tmp_path: Path, monkeypatch):
    harness, base = _harness(tmp_path)
    store_path = _set_store(base, monkeypatch)
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
