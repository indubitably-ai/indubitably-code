from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import ValidationError

from tools.schemas import DeleteFileInput
from session.turn_diff_tracker import TurnDiffTracker


def delete_file_tool_def() -> dict:
    return {
        "name": "delete_file",
        "description": "Delete a file at the specified path. Fails gracefully if it does not exist.",
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "path": {"type": "string", "description": "File path to delete."},
            },
            "required": ["path"],
        },
    }


def delete_file_impl(input: Dict[str, Any], tracker: Optional[TurnDiffTracker] = None) -> str:
    try:
        params = DeleteFileInput(**input)
    except ValidationError as exc:
        messages = []
        for err in exc.errors():
            loc = ".".join(str(part) for part in err.get("loc", ())) or "input"
            messages.append(f"{loc}: {err.get('msg', 'invalid value')}")
        raise ValueError("; ".join(messages)) from exc

    path = params.path.strip()
    target = Path(path)

    if target.exists() and target.is_dir():
        return json.dumps({"ok": False, "error": "path is a directory", "path": path})

    old_content: Optional[str] = None
    if target.exists() and not target.is_dir():
        try:
            old_content = target.read_text(encoding="utf-8")
        except Exception:
            old_content = None

    try:
        if tracker is not None:
            tracker.lock_file(target)
        os.remove(target)
        if tracker is not None:
            tracker.record_edit(
                path=target,
                tool_name="delete_file",
                action="delete",
                old_content=old_content,
                new_content=None,
            )
        return json.dumps({"ok": True, "path": path})
    except FileNotFoundError:
        return json.dumps({"ok": True, "path": path, "note": "file did not exist"})
    except Exception as exc:  # pragma: no cover - defensive
        return json.dumps({"ok": False, "path": path, "error": str(exc)})
    finally:
        if tracker is not None:
            tracker.unlock_file(target)
