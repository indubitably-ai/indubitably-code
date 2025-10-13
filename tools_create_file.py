from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from tools.handler import ToolOutput
from tools.schemas import CreateFileInput
from session.turn_diff_tracker import TurnDiffTracker


_IF_EXISTS = {"error", "overwrite", "skip"}


def create_file_tool_def() -> dict:
    return {
        "name": "create_file",
        "description": (
            "Create or ensure a file with the provided content. Supports if-exists policies (error, "
            "overwrite, skip) and optional parent directory creation."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "path": {"type": "string", "description": "Destination file path."},
                "content": {"type": "string", "description": "File contents (defaults to empty string)."},
                "if_exists": {
                    "type": "string",
                    "enum": sorted(_IF_EXISTS),
                    "description": "Behaviour when the file already exists (default error).",
                },
                "create_parents": {
                    "type": "boolean",
                    "description": "Create parent directories if missing (default true).",
                },
                "encoding": {
                    "type": "string",
                    "description": "Text encoding used when writing (default utf-8).",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "When true, validate file creation without writing to disk.",
                },
            },
            "required": ["path"],
        },
    }


def create_file_impl(params: CreateFileInput, tracker: Optional[TurnDiffTracker] = None) -> ToolOutput:
    path_value = params.path.strip()
    policy = params.if_exists
    create_parents = params.create_parents
    encoding = params.encoding or "utf-8"
    content = params.content
    dry_run = params.dry_run

    target = Path(path_value)
    existing = target.exists()
    if existing:
        if target.is_dir():
            raise IsADirectoryError(path_value)
        if policy == "skip":
            result = {"ok": True, "action": "skip", "path": path_value}
            if dry_run:
                result["dry_run"] = True
            return ToolOutput(content=json.dumps(result), success=True)
        if policy == "error":
            return ToolOutput(content=path_value, success=False, metadata={"error_type": "exists"})
        # policy == overwrite proceeds

    parent = target.parent
    if not parent.exists():
        if create_parents:
            if not dry_run:
                parent.mkdir(parents=True, exist_ok=True)
        else:
            return ToolOutput(content=f"parent directory missing: {parent}", success=False, metadata={"error_type": "not_found"})

    bytes_written = len(content.encode(encoding, errors="replace"))
    previous_content: Optional[str] = None
    if existing and not dry_run:
        try:
            previous_content = target.read_text(encoding=encoding)
        except Exception:
            previous_content = None

    if dry_run:
        return ToolOutput(content=json.dumps({
            "ok": True,
            "action": "overwrite" if existing else "create",
            "path": path_value,
            "encoding": encoding,
            "bytes_written": bytes_written,
            "dry_run": True,
        }), success=True)

    if tracker is not None and not dry_run:
        tracker.lock_file(target)

    try:
        target.write_text(content, encoding=encoding)
    finally:
        if tracker is not None and not dry_run:
            tracker.unlock_file(target)

    if tracker is not None and not dry_run:
        tracker.record_edit(
            path=target,
            tool_name="create_file",
            action="overwrite" if existing else "create",
            old_content=previous_content,
            new_content=content,
        )

    return ToolOutput(content=json.dumps({
        "ok": True,
        "action": "overwrite" if existing else "create",
        "path": path_value,
        "encoding": encoding,
        "bytes_written": bytes_written,
    }), success=True)
