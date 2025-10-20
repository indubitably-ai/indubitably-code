import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from tools.schemas import TODO_STATUSES, TodoWriteInput
from session.turn_diff_tracker import TurnDiffTracker
from tools.handler import ToolOutput


_STORE_PATH = Path(".session_todos.json")


def todo_write_tool_def() -> dict:
    return {
        "name": "todo_write",
        "description": (
            "Maintain a lightweight, session-scoped TODO list that agents can update incrementally. Provide `merge` to control behavior: true merges incoming items (by `id`) into the existing set, "
            "preserving unspecified fields, while false replaces the store entirely. The `todos` array accepts objects containing `id`, optional `content`, and `status` drawn from the allowed enum so downstream "
            "interfaces can render consistent progress. The tool persists data in .session_todos.json, timestamps updates, and records diffs via TurnDiffTracker when available. Example: to mark a task complete, call todo_write with merge=true and todos=[{'id': 'tests', 'status': 'completed'}]. "
            "Avoid using this tool for persistent project management (it is scoped to the current workspace run), for high-volume notes (prefer a markdown document), or with duplicate IDs across different intents."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "merge": {"type": "boolean", "description": "If true, merge into existing list; else replace."},
                "todos": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "id": {"type": "string", "description": "Unique identifier for the todo."},
                            "content": {"type": "string", "description": "Short, action-oriented description."},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed", "cancelled"],
                                "description": "Current status of the todo.",
                            },
                        },
                        "required": ["id"],
                    },
                    "description": "Array of todo items to write to the store.",
                },
            },
            "required": ["merge", "todos"],
        },
    }


def _load_store() -> Dict[str, Any]:
    if not _STORE_PATH.exists():
        return {"todos": [], "updated_at": None}
    try:
        data = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"todos": [], "updated_at": None}
        data.setdefault("todos", [])
        data.setdefault("updated_at", None)
        return data
    except Exception:
        return {"todos": [], "updated_at": None}


def _save_store(store: Dict[str, Any]) -> None:
    store["updated_at"] = int(time.time() * 1000)
    _STORE_PATH.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")


def _validate_status(status: Optional[str]) -> Optional[str]:
    if status is None:
        return None
    if status not in TODO_STATUSES:
        raise ValueError(f"invalid status: {status}")
    return status


def _merge_todos(existing: List[Dict[str, Any]], incoming: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id = {t.get("id"): {"id": t.get("id"), "content": t.get("content", ""), "status": t.get("status", "pending")} for t in existing if t.get("id")}
    for t in incoming:
        tid = t.get("id")
        if not tid:
            continue
        content = t.get("content")
        status = _validate_status(t.get("status"))
        if tid in by_id:
            if content is not None:
                by_id[tid]["content"] = content
            if status is not None:
                by_id[tid]["status"] = status
        else:
            by_id[tid] = {"id": tid, "content": content or "", "status": status or "pending"}
    return list(by_id.values())


def _replace_todos(incoming: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    replaced: List[Dict[str, Any]] = []
    for t in incoming:
        tid = t.get("id")
        if not tid:
            continue
        content = t.get("content", "")
        status = _validate_status(t.get("status") or "pending") or "pending"
        replaced.append({"id": tid, "content": content, "status": status})
    return replaced


def todo_write_impl(params: TodoWriteInput, tracker: Optional[TurnDiffTracker] = None) -> ToolOutput:
    merge = params.merge
    todos_in = [todo.dump() for todo in params.todos]

    store = _load_store()
    existing: List[Dict[str, Any]] = store.get("todos", [])

    try:
        updated = _merge_todos(existing, todos_in) if merge else _replace_todos(todos_in)
    except ValueError as exc:
        return ToolOutput(content=str(exc), success=False, metadata={"error_type": "validation"})

    store["todos"] = updated
    old_text: Optional[str] = None
    if _STORE_PATH.exists():
        try:
            old_text = _STORE_PATH.read_text(encoding="utf-8")
        except Exception:
            old_text = None

    if tracker is not None:
        tracker.lock_file(_STORE_PATH)
    try:
        _save_store(store)
        if tracker is not None:
            new_text = json.dumps(store, ensure_ascii=False)
            tracker.record_edit(
                path=_STORE_PATH,
                tool_name="todo_write",
                action="update",
                old_content=old_text,
                new_content=new_text,
            )
    finally:
        if tracker is not None:
            tracker.unlock_file(_STORE_PATH)

    return ToolOutput(content=json.dumps(store), success=True)
