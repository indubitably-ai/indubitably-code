import os
import json
from pathlib import Path
from typing import Dict, Any, List, Tuple


HEADER_PREFIX = "*** "
FILE_MARKER = " File: "


def apply_patch_tool_def() -> dict:
    return {
        "name": "apply_patch",
        "description": (
            "Apply a structured V4A-style diff to a single file. Supports Add, Update, and Delete actions. "
            "Update supports multiple single-line replacements using '- ' for removals and '+ ' for additions."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "file_path": {"type": "string", "description": "Path to the target file to patch."},
                "patch": {"type": "string", "description": "V4A-style diff patch text."},
            },
            "required": ["file_path", "patch"],
        },
    }


def _parse_header(patch: str) -> Tuple[str, str]:
    for line in patch.splitlines():
        if line.startswith(HEADER_PREFIX) and FILE_MARKER in line:
            # Example: *** Add File: path/to/file
            parts = line[len(HEADER_PREFIX):].split(FILE_MARKER, 1)
            if len(parts) == 2:
                action = parts[0].strip().split()[0]  # Add | Update | Delete
                file_in_header = parts[1].strip()
                return action, file_in_header
    return "", ""


def _extract_add_content(patch: str) -> str:
    content_lines: List[str] = []
    for line in patch.splitlines():
        if line.startswith(HEADER_PREFIX) or line.startswith("@@"):
            continue
        if line.startswith("- ") or line.startswith("+ "):
            # diff lines are not treated as literal content for Add
            continue
        content_lines.append(line)
    return "\n".join(content_lines).rstrip("\n") + "\n"


def _collect_line_replacements(patch: str) -> List[Tuple[str, str]]:
    old_lines: List[str] = []
    new_lines: List[str] = []
    for line in patch.splitlines():
        if line.startswith("- "):
            old_lines.append(line[2:])
        elif line.startswith("+ "):
            new_lines.append(line[2:])
    # Pair by index; ignore extras if unbalanced
    pairs: List[Tuple[str, str]] = []
    for i in range(min(len(old_lines), len(new_lines))):
        pairs.append((old_lines[i], new_lines[i]))
    return pairs


def _ensure_parent_dirs(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def apply_patch_impl(input: Dict[str, Any]) -> str:
    file_path = input.get("file_path", "").strip()
    patch = input.get("patch", "")
    if not file_path or not patch:
        raise ValueError("missing 'file_path' or 'patch'")

    target = Path(file_path)
    action, header_path = _parse_header(patch)

    # If header path is present and differs, prefer explicit input file_path but note it
    if header_path and os.path.normpath(header_path) != os.path.normpath(file_path):
        # Proceed but include a warning in the result
        header_mismatch = True
    else:
        header_mismatch = False

    if action.lower() == "delete":
        try:
            target.unlink()
            return json.dumps({"ok": True, "action": "Delete", "path": file_path})
        except FileNotFoundError:
            return json.dumps({"ok": True, "action": "Delete", "path": file_path, "note": "file did not exist"})
        except Exception as e:
            return json.dumps({"ok": False, "action": "Delete", "path": file_path, "error": str(e)})

    if action.lower() == "add":
        try:
            _ensure_parent_dirs(target)
            content = _extract_add_content(patch)
            target.write_text(content, encoding="utf-8")
            result = {"ok": True, "action": "Add", "path": file_path}
            if header_mismatch:
                result["warning"] = "header file path mismatched input file_path"
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"ok": False, "action": "Add", "path": file_path, "error": str(e)})

    # Default to Update when header missing or 'Update'
    try:
        existing = ""
        if target.exists():
            existing = target.read_text(encoding="utf-8")
        else:
            # For Update on non-existent file, treat as Add with whole content if no +/- pairs
            existing = ""

        replacements = _collect_line_replacements(patch)
        if replacements:
            new_content = existing
            for old_line, new_line in replacements:
                if old_line not in new_content:
                    raise ValueError(f"old line not found: {old_line!r}")
                new_content = new_content.replace(old_line, new_line, 1)
        else:
            # No explicit +/- lines; assume full content replacement body after headers
            new_content = _extract_add_content(patch)

        _ensure_parent_dirs(target)
        target.write_text(new_content, encoding="utf-8")
        result = {"ok": True, "action": "Update", "path": file_path}
        if header_mismatch:
            result["warning"] = "header file path mismatched input file_path"
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"ok": False, "action": "Update", "path": file_path, "error": str(e)})
