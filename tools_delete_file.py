import os
import json
from pathlib import Path
from typing import Dict, Any


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


def delete_file_impl(input: Dict[str, Any]) -> str:
    path = (input.get("path") or "").strip()
    if not path:
        raise ValueError("missing 'path'")

    p = Path(path)

    # Guardrails: only allow deleting files, not directories
    if p.exists() and p.is_dir():
        return json.dumps({"ok": False, "error": "path is a directory", "path": path})

    try:
        os.remove(p)
        return json.dumps({"ok": True, "path": path})
    except FileNotFoundError:
        return json.dumps({"ok": True, "path": path, "note": "file did not exist"})
    except Exception as e:
        return json.dumps({"ok": False, "path": path, "error": str(e)})
