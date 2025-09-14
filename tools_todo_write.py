import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional


_STORE_PATH = Path(".session_todos.json")
_ALLOWED_STATUSES = {"pending", "in_progress", "completed", "cancelled"}


def todo_write_tool_def() -> dict:
    return {
        "name": "todo_write",
        "description": (
            "Create/update a structured TODO list for the current session. "
            "When merge=true, todos are merged by id; unspecified fields remain unchanged. "
            "When merge=false, the provided list replaces the current list."
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
    if status not in _ALLOWED_STATUSES:
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


def todo_write_impl(input: Dict[str, Any]) -> str:
    merge = bool(input.get("merge", False))
    todos_in = input.get("todos") or []
    if not isinstance(todos_in, list):
        raise ValueError("'todos' must be an array")

    store = _load_store()
    existing: List[Dict[str, Any]] = store.get("todos", [])

    updated = _merge_todos(existing, todos_in) if merge else _replace_todos(todos_in)

    store["todos"] = updated
    _save_store(store)

    return json.dumps(store)
