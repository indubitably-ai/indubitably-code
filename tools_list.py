import os
import json
from typing import Dict, Any, List


def list_files_tool_def() -> dict:
    return {
        "name": "list_files",
        "description": "List files and directories at a given path. If path omitted, list current directory.",
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Optional relative path. Defaults to current directory.",
                }
            },
        },
    }


def list_files_impl(input: Dict[str, Any]) -> str:
    start = input.get("path") or "."
    results: List[str] = []

    for root, dirs, files in os.walk(start):
        rel_root = os.path.relpath(root, start)

        def append_entry(name: str, is_dir: bool) -> None:
            rel_path = name if rel_root == "." else os.path.join(rel_root, name)
            results.append(rel_path + ("/" if is_dir else ""))

        for d in dirs:
            append_entry(d, True)
        for f in files:
            append_entry(f, False)

    return json.dumps(results)


