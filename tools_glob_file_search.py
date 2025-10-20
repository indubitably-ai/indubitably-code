import os
import json
import glob
from typing import Dict, Any, List
from tools.handler import ToolOutput
from tools.schemas import GlobFileSearchInput


def glob_file_search_tool_def() -> dict:
    return {
        "name": "glob_file_search",
        "description": (
            "Locate files whose paths match a shell-style glob expression, useful when you know part of a filename but not its exact location. Provide a `glob_pattern` such as '*.py' or 'migrations/**/*.sql'; "
            "the tool will automatically prepend '**/' so the search recurses from the chosen `target_directory` (defaults to cwd). Matches are filtered to regular files, sorted by modification time "
            "(newest first), converted to repo-relative paths, and optionally truncated with `head_limit`. Example: call glob_file_search with glob_pattern='**/Dockerfile' to find docker definitions scattered across packages. "
            "Avoid using this for content search (use grep or codebase_search instead), for directory discovery, or when large unbounded patterns would enumerate millions of files without additional narrowing."
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


def glob_file_search_impl(params: GlobFileSearchInput) -> ToolOutput:
    try:
        base_dir = params.target_directory or "."
        pattern = (params.glob_pattern or "").strip()
        head_limit = params.head_limit

        norm = _normalize_pattern(pattern)
        search_expr = os.path.join(base_dir, norm)
        matches = glob.glob(search_expr, recursive=True)

        file_matches = [m for m in matches if os.path.isfile(m)]
        sorted_paths = _sort_by_mtime(file_matches)
        cwd = os.getcwd()
        rel_paths = [os.path.relpath(p, cwd) for p in sorted_paths]
        if head_limit is not None:
            rel_paths = rel_paths[:head_limit]

        return ToolOutput(content=json.dumps(rel_paths), success=True)
    except Exception as exc:
        return ToolOutput(content=f"Glob search failed: {exc}", success=False, metadata={"error_type": "search_error"})
