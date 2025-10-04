from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict


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


def rename_file_impl(input: Dict[str, Any]) -> str:
    source_value = (input.get("source_path") or "").strip()
    dest_value = (input.get("dest_path") or "").strip()
    if not source_value or not dest_value:
        raise ValueError("'source_path' and 'dest_path' are required")

    overwrite = bool(input.get("overwrite", False))
    create_parent = True if input.get("create_dest_parent") is None else bool(input.get("create_dest_parent"))

    dry_run = bool(input.get("dry_run", False))

    source = Path(source_value)
    dest = Path(dest_value)

    if source.resolve() == dest.resolve():
        raise ValueError("source and destination paths are identical")

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

    os.replace(source, dest)

    result = {
        "ok": True,
        "action": "rename",
        "source": source_value,
        "destination": dest_value,
        "overwritten": bool(dest_existed),
    }
    return json.dumps(result)


