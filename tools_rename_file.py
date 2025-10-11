from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import ValidationError

from tools.schemas import RenameFileInput
from session.turn_diff_tracker import TurnDiffTracker


def rename_file_tool_def() -> dict:
    return {
        "name": "rename_file",
        "description": (
            "Rename or move a file. Ensures the source exists, the destination parent directory "
            "is created when requested, and optionally refuses to overwrite existing files."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "source_path": {
                    "type": "string",
                    "description": "Existing file path to rename/move.",
                },
                "dest_path": {
                    "type": "string",
                    "description": "Destination path for the file.",
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "Allow overwriting an existing file at dest_path (default false).",
                },
                "create_dest_parent": {
                    "type": "boolean",
                    "description": "Create parent directories for dest_path when they do not exist (default true).",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "When true, validate the rename without moving files.",
                },
            },
            "required": ["source_path", "dest_path"],
        },
    }


def rename_file_impl(input: Dict[str, Any], tracker: Optional[TurnDiffTracker] = None) -> str:
    try:
        params = RenameFileInput(**input)
    except ValidationError as exc:
        messages = []
        for err in exc.errors():
            loc = ".".join(str(part) for part in err.get("loc", ())) or "input"
            messages.append(f"{loc}: {err.get('msg', 'invalid value')}")
        raise ValueError("; ".join(messages)) from exc

    source_value = params.source_path.strip()
    dest_value = params.dest_path.strip()
    overwrite = params.overwrite
    create_parent = params.create_dest_parent
    dry_run = params.dry_run

    source = Path(source_value)
    dest = Path(dest_value)

    if not source.exists():
        raise FileNotFoundError(source_value)
    if source.is_dir():
        raise IsADirectoryError("source path is a directory")

    dest_existed = dest.exists()
    if dest_existed:
        if not overwrite:
            raise FileExistsError(dest_value)
        if dest.is_dir():
            raise IsADirectoryError("destination path is a directory")

    dest_parent = dest.parent
    if not dest_parent.exists():
        if create_parent:
            if not dry_run:
                dest_parent.mkdir(parents=True, exist_ok=True)
        else:
            raise FileNotFoundError(f"destination parent missing: {dest_parent}")

    if dry_run:
        return json.dumps({
            "ok": True,
            "action": "rename",
            "source": source_value,
            "destination": dest_value,
            "overwritten": bool(dest_existed),
            "dry_run": True,
        })

    if tracker is not None:
        tracker.lock_file(source)
        dest_locked = False
        if source.resolve() != dest.resolve():
            tracker.lock_file(dest)
            dest_locked = True
    else:
        dest_locked = False

    try:
        os.replace(source, dest)
        if tracker is not None:
            tracker.record_edit(
                path=source,
                tool_name="rename_file",
                action="rename",
                old_content=source_value,
                new_content=dest_value,
            )
    finally:
        if tracker is not None:
            tracker.unlock_file(source)
            if dest_locked:
                tracker.unlock_file(dest)

    result = {
        "ok": True,
        "action": "rename",
        "source": source_value,
        "destination": dest_value,
        "overwritten": bool(dest_existed),
    }
    return json.dumps(result)
