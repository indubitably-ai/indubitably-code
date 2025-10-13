import os
import json
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from tools.handler import ToolOutput
from tools.schemas import ListFilesInput
from fnmatch import fnmatch


_DEF_IGNORES = {".git", ".hg", ".svn", "node_modules", "target", "dist", "build", ".venv", "__pycache__"}


def list_files_tool_def() -> dict:
    return {
        "name": "list_files",
        "description": (
            "List files and directories at a given path. Defaults to recursive listing. "
            "Supports depth limits, glob and ignore filters, sorting, and head limiting."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Optional base path. Defaults to current directory.",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Recurse into subdirectories (default true).",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum recursion depth relative to base (1 lists only immediate entries).",
                    "minimum": 1,
                },
                "glob": {
                    "type": "string",
                    "description": "Optional glob filter applied to relative paths (e.g., **/*.py).",
                },
                "ignore_globs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Patterns to exclude (e.g., **/node_modules/**).",
                },
                "include_files": {
                    "type": "boolean",
                    "description": "Include files (default true).",
                },
                "include_dirs": {
                    "type": "boolean",
                    "description": "Include directories (default true).",
                },
                "sort_by": {
                    "type": "string",
                    "enum": ["name", "mtime", "size"],
                    "description": "Sort key (default name).",
                },
                "sort_order": {
                    "type": "string",
                    "enum": ["asc", "desc"],
                    "description": "Sort order (default asc).",
                },
                "head_limit": {
                    "type": "integer",
                    "description": "Return at most N entries.",
                    "minimum": 1,
                },
            },
        },
    }


def _within_depth(root: Path, base: Path, max_depth: Optional[int]) -> bool:
    if max_depth is None:
        return True
    # Depth of entries under base: base itself depth 0, its children 1, etc.
    root_depth = len(root.parts) - len(base.parts)
    return root_depth < max_depth


def _should_ignore_rel(rel_path: str, ignore_globs: List[str]) -> bool:
    for patt in ignore_globs:
        if fnmatch(rel_path, patt):
            return True
    return False


def _gather_entries(start: str, recursive: bool, max_depth: Optional[int], glob_pat: Optional[str], ignore_globs: List[str], include_files: bool, include_dirs: bool, need_stat: bool) -> List[Tuple[str, bool, Optional[float], Optional[int]]]:
    base = Path(start)
    results: List[Tuple[str, bool, Optional[float], Optional[int]]] = []

    # If non-recursive: use scandir for speed
    if not recursive:
        with os.scandir(base) as it:
            for entry in it:
                rel = entry.name
                rel_path = rel
                is_dir = entry.is_dir(follow_symlinks=False)
                if _should_ignore_rel(rel_path, ignore_globs):
                    continue
                if glob_pat and not fnmatch(rel_path, glob_pat):
                    continue
                if (is_dir and not include_dirs) or ((not is_dir) and not include_files):
                    continue
                mtime = os.path.getmtime(entry.path) if need_stat else None
                size = (entry.stat().st_size if need_stat and not is_dir else None)
                results.append((rel_path + ("/" if is_dir else ""), is_dir, mtime, size))
        return results

    # Recursive walk with pruning and relative paths
    for root, dirs, files in os.walk(base, topdown=True):
        root_path = Path(root)
        # Depth pruning
        if max_depth is not None and not _within_depth(root_path, base, max_depth):
            dirs[:] = []
            continue

        rel_root = os.path.relpath(root, start)
        rel_root = "." if rel_root == "." else rel_root

        # Prune ignored directories early
        pruned_dirs = []
        for d in list(dirs):
            rel_d = d if rel_root == "." else f"{rel_root}/{d}"
            if d in _DEF_IGNORES or _should_ignore_rel(rel_d + "/", ignore_globs):
                continue
            pruned_dirs.append(d)
        dirs[:] = pruned_dirs

        # Directories as entries
        if include_dirs:
            for d in dirs:
                rel_d = d if rel_root == "." else f"{rel_root}/{d}"
                if glob_pat and not fnmatch(rel_d + "/", glob_pat):
                    continue
                mtime = os.path.getmtime(os.path.join(root, d)) if need_stat else None
                results.append((rel_d + "/", True, mtime, None))

        # Files as entries
        if include_files:
            for f in files:
                rel_f = f if rel_root == "." else f"{rel_root}/{f}"
                if _should_ignore_rel(rel_f, ignore_globs):
                    continue
                if glob_pat and not fnmatch(rel_f, glob_pat):
                    continue
                mtime = os.path.getmtime(os.path.join(root, f)) if need_stat else None
                size = (os.path.getsize(os.path.join(root, f)) if need_stat else None)
                results.append((rel_f, False, mtime, size))

    return results


def list_files_impl(params: ListFilesInput) -> ToolOutput:
    start = params.path or "."
    recursive = params.recursive
    max_depth = params.max_depth
    glob_pat = params.glob
    ignore_globs = params.ignore_globs or []
    include_files = params.include_files
    include_dirs = params.include_dirs
    sort_by = params.sort_by
    sort_order = params.sort_order
    head_limit = params.head_limit

    need_stat = sort_by in ("mtime", "size")

    entries = _gather_entries(
        start=start,
        recursive=recursive,
        max_depth=max_depth,
        glob_pat=glob_pat,
        ignore_globs=ignore_globs,
        include_files=include_files,
        include_dirs=include_dirs,
        need_stat=need_stat,
    )

    reverse = (sort_order == "desc")
    if sort_by == "name":
        entries.sort(key=lambda t: t[0].lower(), reverse=reverse)
    elif sort_by == "mtime":
        entries.sort(key=lambda t: (t[2] or 0.0, t[0].lower()), reverse=reverse)
    elif sort_by == "size":
        entries.sort(key=lambda t: (t[3] or 0, t[0].lower()), reverse=reverse)

    if head_limit is not None:
        entries = entries[:head_limit]

    out: List[str] = [t[0] for t in entries]
    return ToolOutput(content=json.dumps(out), success=True)


