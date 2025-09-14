import os
import json
import glob
from typing import Dict, Any, List


def glob_file_search_tool_def() -> dict:
    return {
        "name": "glob_file_search",
        "description": (
            "Find files by name using a glob pattern. Automatically searches recursively and returns matches "
            "sorted by modification time (newest first)."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "target_directory": {
                    "type": "string",
                    "description": "Optional base directory to search from. Defaults to current directory.",
                },
                "glob_pattern": {
                    "type": "string",
                    "description": "Glob pattern (e.g., *.py, migrations/**/*.sql). '**/' is auto-prepended if missing.",
                },
                "head_limit": {
                    "type": "integer",
                    "description": "Limit the number of returned paths.",
                    "minimum": 1,
                },
            },
            "required": ["glob_pattern"],
        },
    }


def _normalize_pattern(pattern: str) -> str:
    p = pattern.strip()
    if not p:
        return p
    # Auto-prepend **/ if pattern doesn't start with it
    if not p.startswith("**/"):
        p = f"**/{p}"
    return p


def _sort_by_mtime(paths: List[str]) -> List[str]:
    try:
        return sorted(paths, key=lambda p: os.path.getmtime(p), reverse=True)
    except Exception:
        # Fallback to lexical order if mtime fails for any path
        return sorted(paths)


def glob_file_search_impl(input: Dict[str, Any]) -> str:
    base_dir = input.get("target_directory") or "."
    pattern = input.get("glob_pattern", "").strip()
    if not pattern:
        raise ValueError("missing 'glob_pattern'")

    head_limit = input.get("head_limit")
    if head_limit is not None:
        head_limit = int(head_limit)
        if head_limit <= 0:
            head_limit = None

    norm = _normalize_pattern(pattern)

    search_expr = os.path.join(base_dir, norm)
    matches = glob.glob(search_expr, recursive=True)

    # Only include files (not directories)
    file_matches = [m for m in matches if os.path.isfile(m)]

    # Sort by modification time (newest first)
    sorted_paths = _sort_by_mtime(file_matches)

    # Return paths relative to the workspace root for compatibility with read_file
    cwd = os.getcwd()
    rel_paths = [os.path.relpath(p, cwd) for p in sorted_paths]

    if head_limit is not None:
        rel_paths = rel_paths[:head_limit]

    return json.dumps(rel_paths)
