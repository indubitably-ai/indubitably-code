import os
import json
import time
from typing import Dict, Any, List, Tuple, Optional


_IGNORED_DIRS = {".git", ".hg", ".svn", "node_modules", "target", "dist", "build", ".venv", "__pycache__"}
_ALLOWED_EXTS = {
    ".rs", ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".kt", ".swift",
    ".c", ".h", ".cpp", ".hpp", ".cs", ".rb", ".php", ".sh", ".md", ".toml", ".yaml", ".yml"
}


def codebase_search_tool_def() -> dict:
    return {
        "name": "codebase_search",
        "description": (
            "Heuristic semantic-like search over the codebase. Finds likely relevant files/snippets for a natural "
            "language query by scoring filenames, paths, and content. Returns top matches with snippets."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string", "description": "Natural language or keyword query."},
                "target_directories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional base directories to search. Defaults to current directory.",
                },
                "glob_pattern": {
                    "type": "string",
                    "description": "Optional glob pattern to restrict files (e.g., src/**/*.rs).",
                },
                "max_results": {"type": "integer", "description": "Max number of results.", "minimum": 1, "default": 10},
                "snippet_lines": {"type": "integer", "description": "Context lines around matches.", "minimum": 0, "default": 2},
            },
            "required": ["query"],
        },
    }


def _should_skip_dir(dirname: str) -> bool:
    return dirname in _IGNORED_DIRS


def _is_allowed_file(path: str) -> bool:
    _, ext = os.path.splitext(path)
    return ext.lower() in _ALLOWED_EXTS


def _iter_files(bases: List[str], glob_pattern: Optional[str]) -> List[str]:
    from fnmatch import fnmatch

    if not bases:
        bases = ["."]

    files: List[str] = []
    for base in bases:
        for root, dirs, filenames in os.walk(base):
            dirs[:] = [d for d in dirs if not _should_skip_dir(d)]
            for f in filenames:
                full = os.path.join(root, f)
                if not _is_allowed_file(full):
                    continue
                if glob_pattern and not fnmatch(full, glob_pattern):
                    continue
                files.append(full)
    return files


def _read_lines(path: str) -> List[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()
    except Exception:
        return []


def _score_and_matches(path: str, lines: List[str], query: str) -> Tuple[float, List[Tuple[int, str]]]:
    ql = query.lower().strip()
    if not ql:
        return 0.0, []

    tokens = [t for t in ql.replace("/", " ").replace("\\", " ").split() if t]

    score = 0.0
    matches: List[Tuple[int, str]] = []

    # Path/filename boosts
    pl = path.lower()
    if ql in pl:
        score += 8.0
    for t in tokens:
        if t in pl:
            score += 3.0

    # Content scoring
    for idx, line in enumerate(lines, start=1):
        ll = line.lower()
        line_score = 0.0
        if ql and ql in ll:
            line_score += 2.5
        for t in tokens:
            if t in ll:
                line_score += 1.0
        if line_score > 0.0:
            score += line_score
            matches.append((idx, line))

    # Recency slight boost to prefer recently modified files when scores tie
    try:
        mtime = os.path.getmtime(path)
        # scale to ~0..1 by comparing to current time horizon
        age_days = max(0.0, (time.time() - mtime) / 86400.0)
        recency_boost = max(0.0, 1.0 - min(age_days / 90.0, 1.0))  # within ~3 months
        score += 0.5 * recency_boost
    except Exception:
        pass

    return score, matches


def _build_snippet(path: str, lines: List[str], match_lines: List[int], context: int, max_lines: int = 40) -> str:
    if not match_lines:
        return path
    used = 0
    out: List[str] = [path]
    seen_blocks: List[Tuple[int, int]] = []

    # Merge overlapping windows
    for ln in match_lines:
        start = max(1, ln - context)
        end = min(len(lines), ln + context)
        if seen_blocks and start <= seen_blocks[-1][1] + 1:
            prev_start, prev_end = seen_blocks[-1]
            seen_blocks[-1] = (prev_start, max(prev_end, end))
        else:
            seen_blocks.append((start, end))

    for start, end in seen_blocks:
        for i in range(start, end + 1):
            prefix = ":" if i in match_lines else "-"
            out.append(f"{prefix}{i}:{lines[i-1]}")
            used += 1
            if used >= max_lines:
                break
        if used >= max_lines:
            break

    return "\n".join(out)


def codebase_search_impl(input: Dict[str, Any]) -> str:
    query = input.get("query", "").strip()
    if not query:
        raise ValueError("missing 'query'")

    bases = input.get("target_directories") or []
    glob_pattern = input.get("glob_pattern")
    max_results = int(input.get("max_results") or 10)
    snippet_lines = int(input.get("snippet_lines") or 2)

    files = _iter_files(bases, glob_pattern)

    scored: List[Tuple[float, str, List[Tuple[int, str]]]] = []
    for path in files:
        lines = _read_lines(path)
        score, matches = _score_and_matches(path, lines, query)
        if score > 0 and matches:
            scored.append((score, path, matches))

    # Sort by score desc, then by recency (mtime)
    scored.sort(key=lambda t: (t[0], os.path.getmtime(t[1]) if os.path.exists(t[1]) else 0), reverse=True)

    results = []
    for score, path, matches in scored[:max_results]:
        match_line_numbers = [ln for ln, _ in matches]
        snippet = _build_snippet(path, _read_lines(path), match_line_numbers, snippet_lines)
        results.append({
            "path": path,
            "score": round(score, 3),
            "matches": [{"line": ln, "text": txt} for ln, txt in matches[:10]],
            "snippet": snippet,
        })

    return json.dumps({"query": query, "results": results})
