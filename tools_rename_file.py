from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from tools.handler import ToolOutput
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


def rename_file_impl(params: RenameFileInput, tracker: Optional[TurnDiffTracker] = None) -> ToolOutput:
    source_value = params.source_path.strip()
    dest_value = params.dest_path.strip()
    overwrite = params.overwrite
    create_parent = params.create_dest_parent
    dry_run = params.dry_run

    source = Path(source_value)
    dest = Path(dest_value)

    if not source.exists():
        return ToolOutput(content=source_value, success=False, metadata={"error_type": "not_found"})
    if source.is_dir():
        return ToolOutput(content="source path is a directory", success=False, metadata={"error_type": "is_directory"})

    dest_existed = dest.exists()
    if dest_existed:
        if not overwrite:
            return ToolOutput(content=dest_value, success=False, metadata={"error_type": "exists"})
        if dest.is_dir():
            return ToolOutput(content="destination path is a directory", success=False, metadata={"error_type": "is_directory"})

    dest_parent = dest.parent
    if not dest_parent.exists():
        if create_parent:
            if not dry_run:
                dest_parent.mkdir(parents=True, exist_ok=True)
        else:
            return ToolOutput(content=f"destination parent missing: {dest_parent}", success=False, metadata={"error_type": "not_found"})

    if dry_run:
        return ToolOutput(content=json.dumps({
            "ok": True,
            "action": "rename",
            "source": source_value,
            "destination": dest_value,
            "overwritten": bool(dest_existed),
            "dry_run": True,
        }), success=True)

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
            try:
                dest_resolved = dest.resolve()
            except FileNotFoundError:
                dest_resolved = dest
            tracker.record_edit(
                path=source,
                tool_name="rename_file",
                action="rename",
                old_content=str(source.resolve()),
                new_content=str(dest_resolved),
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
    return ToolOutput(content=json.dumps(result), success=True)
