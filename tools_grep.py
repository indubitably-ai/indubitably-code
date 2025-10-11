from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Pattern

from pydantic import ValidationError

from tools.schemas import GrepInput


def grep_tool_def() -> dict:
    return {
        "name": "grep",
        "description": (
            "Search file contents using a regular expression. Respects .gitignore implicitly by walking the tree "
            "and skipping common VCS and dependency directories. Use for exact or regex content matches."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "pattern": {"type": "string", "description": "Regular expression pattern (Python regex syntax)."},
                "path": {"type": "string", "description": "Optional base path to search from. Defaults to current directory."},
                "glob": {"type": "string", "description": "Optional filename glob filter like *.py or **/migrations/*.sql"},
                "output_mode": {"type": "string", "enum": ["content", "files_with_matches", "count"], "default": "content"},
                "-B": {"type": "integer", "description": "Lines of context before match (only for content mode).", "minimum": 0},
                "-A": {"type": "integer", "description": "Lines of context after match (only for content mode).", "minimum": 0},
                "-C": {"type": "integer", "description": "Lines of context before/after (only for content mode).", "minimum": 0},
                "-i": {"type": "boolean", "description": "Case-insensitive search."},
                "multiline": {"type": "boolean", "description": "Enable dot to match newlines."},
                "head_limit": {"type": "integer", "description": "Limit the number of output lines or entries.", "minimum": 1}
            },
            "required": ["pattern"],
        },
    }


_IGNORED_DIRS = {".git", ".hg", ".svn", "node_modules", "target", "dist", "build", ".venv", "__pycache__"}


def _should_skip_dir(dirname: str) -> bool:
    return dirname in _IGNORED_DIRS


def _iter_files(base: str, glob: Optional[str]) -> List[str]:
    from fnmatch import fnmatch

    start = base or "."
    results: List[str] = []

    for root, dirs, files in os.walk(start):
        dirs[:] = [d for d in dirs if not _should_skip_dir(d)]

        for f in files:
            rel = os.path.join(root, f)
            if glob and not fnmatch(rel, glob):
                continue
            results.append(rel)
    return results


def _compile_pattern(pat: str, ignore_case: bool, multiline: bool) -> Pattern[str]:
    flags = 0
    if ignore_case:
        flags |= re.IGNORECASE
    if multiline:
        flags |= re.DOTALL
    return re.compile(pat, flags)


def _read_lines(path: str) -> List[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()
    except Exception:
        return []


def _find_matches_in_file(path: str, regex: Pattern[str], before: int, after: int, around: int, head_limit: Optional[int]) -> List[str]:
    lines = _read_lines(path)
    if not lines:
        return []

    content = "\n".join(lines)
    out: List[str] = []

    if around > 0:
        before = after = around

    for m in regex.finditer(content):
        if head_limit is not None and len(out) >= head_limit:
            break
        start_idx = m.start()
        line_no = content.count("\n", 0, start_idx) + 1

        start_line = max(1, line_no - before)
        end_line = min(len(lines), line_no + after)

        out.append(f"{path}")
        for i in range(start_line, end_line + 1):
            prefix = ":" if i == line_no else "-"
            out.append(f"{prefix}{i}:{lines[i-1]}")

    return out


def _collect_files_with_matches(files: List[str], regex: Pattern[str], head_limit: Optional[int]) -> List[str]:
    results: List[str] = []
    for path in files:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                if regex.search(f.read()):
                    results.append(path)
                    if head_limit is not None and len(results) >= head_limit:
                        break
        except Exception:
            continue
    return results


def _count_matches(files: List[str], regex: Pattern[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for path in files:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                counts[path] = len(list(regex.finditer(f.read())))
        except Exception:
            continue
    return counts


def grep_impl(input: Dict[str, Any]) -> str:
    try:
        params = GrepInput(**input)
    except ValidationError as exc:
        messages = []
        for err in exc.errors():
            loc = ".".join(str(part) for part in err.get("loc", ())) or "input"
            messages.append(f"{loc}: {err.get('msg', 'invalid value')}")
        raise ValueError("; ".join(messages)) from exc

    base = params.path or "."
    glob = params.include
    output_mode = params.output_mode
    before = params.before
    after = params.after
    around = params.around
    ignore_case = params.case_insensitive
    multiline = params.multiline
    head_limit = params.head_limit

    regex = _compile_pattern(params.pattern, ignore_case, multiline)

    files = _iter_files(base, glob)

    if output_mode == "files_with_matches":
        matches = _collect_files_with_matches(files, regex, head_limit)
        return json.dumps(matches)
    if output_mode == "count":
        counts = _count_matches(files, regex)
        return json.dumps(counts)

    lines: List[str] = []
    for path in files:
        chunk = _find_matches_in_file(path, regex, before, after, around, head_limit)
        if chunk:
            lines.extend(chunk)
            if head_limit is not None and len(lines) >= head_limit:
                break
    return json.dumps(lines)
