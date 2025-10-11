from __future__ import annotations

import json
import os

from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import ValidationError

from tools.schemas import EditFileInput
from session.turn_diff_tracker import TurnDiffTracker


def edit_file_tool_def() -> dict:
    return {
        "name": "edit_file",
        "description": (
            "Make edits to a text file.\n"
            "Replaces EVERY exact occurrence of 'old_str' (including whitespace) with 'new_str'. "
            "If multiple matches are found, all are replaced and a warning is returned. "
            "'old_str' and 'new_str' MUST be different. "
            "If the file does not exist and old_str == '', the file is created with new_str. "
            "Set dry_run=true to preview replacements and receive structured JSON feedback."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "path": {"type": "string", "description": "The path to the file"},
                "old_str": {"type": "string", "description": "Exact text to replace (must match exactly)"},
                "new_str": {"type": "string", "description": "Replacement text"},
                "dry_run": {
                    "type": "boolean",
                    "description": "When true, validate the edit without writing changes.",
                },
            },
            "required": ["path", "old_str", "new_str"],
        },
    }



_LARGE_FILE_WARNING_LINES = 2000


def _build_response(
    action: str,
    path: str,
    *,
    dry_run: bool = False,
    replacements: int | None = None,
    warning: str | None = None,
) -> str:
    payload: Dict[str, Any] = {"ok": True, "action": action, "path": path}
    if dry_run:
        payload["dry_run"] = True
    if replacements is not None:
        payload["replacements"] = replacements
    if warning:
        payload["warning"] = warning
    return json.dumps(payload)


def _create_new_file(
    file_path: str,
    content: str,
    *,
    dry_run: bool = False,
    tracker: Optional[TurnDiffTracker] = None,
) -> str:
    if dry_run:
        return _build_response("create", file_path, dry_run=True)
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if tracker is not None:
        tracker.lock_file(p)
    try:
        p.write_text(content, encoding="utf-8")
    finally:
        if tracker is not None:
            tracker.unlock_file(p)

    if tracker is not None:
        tracker.record_edit(
            path=p,
            tool_name="edit_file",
            action="create",
            old_content=None,
            new_content=content,
        )
    return _build_response("create", file_path)



def edit_file_impl(input: Dict[str, Any], tracker: Optional[TurnDiffTracker] = None) -> str:
    try:
        params = EditFileInput(**input)
    except ValidationError as exc:
        messages = []
        for err in exc.errors():
            loc = ".".join(str(part) for part in err.get("loc", ())) or "input"
            messages.append(f"{loc}: {err.get('msg', 'invalid value')}")
        raise ValueError("; ".join(messages)) from exc

    path = params.path
    old = params.old_str
    new = params.new_str
    dry_run = params.dry_run

    if not os.path.exists(path):
        if old == "":
            return _create_new_file(path, new, dry_run=dry_run, tracker=tracker)
        raise FileNotFoundError(path)

    content = Path(path).read_text(encoding="utf-8")
    line_total = max(1, content.count("\n") + 1)
    warning = None
    if line_total >= _LARGE_FILE_WARNING_LINES:
        warning = f"file has {line_total} lines; consider template_block for large edits"

    if old == "":
        if dry_run:
            return _build_response("replace", path, dry_run=True, warning=warning)
        if tracker is not None:
            tracker.lock_file(path)
        try:
            Path(path).write_text(new, encoding="utf-8")
        finally:
            if tracker is not None:
                tracker.unlock_file(path)
        if tracker is not None:
            tracker.record_edit(
                path=path,
                tool_name="edit_file",
                action="replace",
                old_content=content,
                new_content=new,
            )
        return _build_response("replace", path, warning=warning)

    occurrences = content.count(old)
    if occurrences == 0:
        raise ValueError("old_str not found in file")

    if occurrences > 1:
        extra = f"multiple matches ({occurrences}); ensure this edit is intended"
        warning = f"{warning}; {extra}" if warning else extra

    new_content = content.replace(old, new)

    if dry_run:
        return _build_response(
            "replace",
            path,
            dry_run=True,
            replacements=occurrences,
            warning=warning,
        )

    if tracker is not None:
        tracker.lock_file(path)
    try:
        Path(path).write_text(new_content, encoding="utf-8")
    finally:
        if tracker is not None:
            tracker.unlock_file(path)

    if tracker is not None:
        tracker.record_edit(
            path=path,
            tool_name="edit_file",
            action="replace",
            old_content=content,
            new_content=new_content,
        )

    return _build_response("replace", path, replacements=occurrences, warning=warning)
