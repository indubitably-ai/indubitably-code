from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from tools.handler import ToolOutput
from tools.schemas import DeleteFileInput
from session.turn_diff_tracker import TurnDiffTracker


def delete_file_tool_def() -> dict:
    return {
        "name": "delete_file",
        "description": (
            "Delete a single regular file from the repository with audit-friendly logging. Pass the `path` to the target file; the tool verifies the path refers to a file (not a directory), "
            "locks it through the TurnDiffTracker, and removes it from disk while emitting JSON indicating the action taken. If the file is already absent the call succeeds with a note so agents "
            "can continue idempotently. Example: removing an obsolete snapshot would involve delete_file with path='tests/__snapshots__/component.snap'. Do not use delete_file to remove directories, "
            "to wipe generated build artifacts en masse, or to circumvent review of large deletions—prefer project-specific cleanup scripts or template_block for inline content removal."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "path": {"type": "string", "description": "File path to delete."},
            },
            "required": ["path"],
        },
    }


def delete_file_impl(params: DeleteFileInput, tracker: Optional[TurnDiffTracker] = None) -> ToolOutput:
    path = params.path.strip()
    target = Path(path)

    if target.exists() and target.is_dir():
        return ToolOutput(content=json.dumps({"ok": False, "error": "path is a directory", "path": path}), success=False, metadata={"error_type": "is_directory"})

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
        return ToolOutput(content=json.dumps({"ok": True, "path": path}), success=True)
    except FileNotFoundError:
        return ToolOutput(content=json.dumps({"ok": True, "path": path, "note": "file did not exist"}), success=True)
    except Exception as exc:  # pragma: no cover - defensive
        return ToolOutput(content=json.dumps({"ok": False, "path": path, "error": str(exc)}), success=False, metadata={"error_type": "delete_error"})
    finally:
        if tracker is not None:
            tracker.unlock_file(target)
