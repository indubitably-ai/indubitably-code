from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


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


def create_file_impl(input: Dict[str, Any]) -> str:
    path_value = (input.get("path") or "").strip()
    if not path_value:
        raise ValueError("'path' is required")

    policy = (input.get("if_exists") or "error").strip().lower()
    if policy not in _IF_EXISTS:
        raise ValueError("invalid if_exists policy")

    create_parents = True if input.get("create_parents") is None else bool(input.get("create_parents"))
    encoding = (input.get("encoding") or "utf-8").strip() or "utf-8"
    content = input.get("content")
    if content is None:
        content = ""

    dry_run = bool(input.get("dry_run", False))

    target = Path(path_value)
    existing = target.exists()
    if existing:
        if target.is_dir():
            raise IsADirectoryError(path_value)
        if policy == "skip":
            result = {"ok": True, "action": "skip", "path": path_value}
            if dry_run:
                result["dry_run"] = True
            return json.dumps(result)
        if policy == "error":
            raise FileExistsError(path_value)
        # policy == overwrite proceeds

    parent = target.parent
    if not parent.exists():
        if create_parents:
            if not dry_run:
                parent.mkdir(parents=True, exist_ok=True)
        else:
            raise FileNotFoundError(f"parent directory missing: {parent}")

    bytes_written = len(content.encode(encoding, errors="replace"))

    if dry_run:
        return json.dumps({
            "ok": True,
            "action": "overwrite" if existing else "create",
            "path": path_value,
            "encoding": encoding,
            "bytes_written": bytes_written,
            "dry_run": True,
        })

    target.write_text(content, encoding=encoding)

    return json.dumps({
        "ok": True,
        "action": "overwrite" if existing else "create",
        "path": path_value,
        "encoding": encoding,
        "bytes_written": bytes_written,
    })


