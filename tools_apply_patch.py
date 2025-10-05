import os
import json
import shutil
import re
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional


HEADER_PREFIX = "*** "
FILE_MARKER = " File: "
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def apply_patch_tool_def() -> dict:
    return {
        "name": "apply_patch",
        "description": (
            "Apply a structured V4A-style diff to a single file. Supports Add, Update, and Delete actions. "
            "Update supports multiple single-line replacements using '- ' for removals and '+ ' for additions. "
            "The tool detects rename hints in unified headers and will instruct you to call rename_file when needed. "
            "Pass dry_run=true to validate the diff without modifying the file; responses include actionable JSON errors when context mismatches occur."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "file_path": {"type": "string", "description": "Path to the target file to patch."},
                "patch": {"type": "string", "description": "V4A-style diff patch text."},
                "dry_run": {
                    "type": "boolean",
                    "description": "Validate patch application without modifying the file when true.",
                },
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


def _parse_unified_diff(patch: str) -> Optional[Dict[str, Any]]:
    lines = [line.rstrip("\n") for line in patch.splitlines()]
    if not any(line.startswith("@@ ") for line in lines):
        return None

    old_file: Optional[str] = None
    new_file: Optional[str] = None
    hunks: List[Dict[str, Any]] = []
    idx = 0
    total = len(lines)

    while idx < total:
        line = lines[idx]
        if line.startswith("--- "):
            old_file = line[4:].strip()
            idx += 1
            continue
        if line.startswith("+++ "):
            new_file = line[4:].strip()
            idx += 1
            continue
        if line.startswith("@@ "):
            match = _HUNK_RE.match(line)
            if not match:
                raise ValueError(f"invalid hunk header: {line}")
            old_start = int(match.group(1))
            old_len = int(match.group(2) or "1")
            new_start = int(match.group(3))
            new_len = int(match.group(4) or "1")
            idx += 1
            hunk_lines: List[Tuple[str, str, bool]] = []
            while idx < total:
                hunk_line = lines[idx]
                if hunk_line.startswith("@@ "):
                    break
                if hunk_line.startswith("--- ") or hunk_line.startswith("+++ "):
                    break
                if hunk_line.startswith("\\ No newline at end of file"):
                    if hunk_lines:
                        sign, text, _ = hunk_lines[-1]
                        hunk_lines[-1] = (sign, text, False)
                    idx += 1
                    continue
                if not hunk_line:
                    # blank lines are context with empty text
                    hunk_lines.append((" ", "", True))
                    idx += 1
                    continue
                sign = hunk_line[0]
                if sign not in {" ", "+", "-"}:
                    raise ValueError(f"invalid hunk line: {hunk_line}")
                hunk_lines.append((sign, hunk_line[1:], True))
                idx += 1
            hunks.append(
                {
                    "old_start": old_start,
                    "old_len": old_len,
                    "new_start": new_start,
                    "new_len": new_len,
                    "lines": hunk_lines,
                }
            )
            continue
        idx += 1

    if not hunks:
        return None
    return {"old_file": old_file, "new_file": new_file, "hunks": hunks}


def _detect_binary_patch(patch: str) -> Optional[str]:
    for marker in ("GIT binary patch", "literal ", "Binary files "):
        if marker in patch:
            return marker.strip()
    return None


def _normalize_compare_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _build_success(action: str, path: str, *, dry_run: bool = False, note: Optional[str] = None) -> str:
    payload = {"ok": True, "action": action, "path": path}
    if dry_run:
        payload["dry_run"] = True
    if note:
        payload["note"] = note
    return json.dumps(payload)


def _build_error(action: str, path: str, message: str, *, dry_run: bool = False) -> str:
    payload = {"ok": False, "action": action, "path": path, "error": message}
    if dry_run:
        payload["dry_run"] = True
    return json.dumps(payload)



def _apply_unified_diff(original: str, hunks: List[Dict[str, Any]]) -> str:
        source_lines = original.splitlines(keepends=True)
        result: List[str] = []
        cursor = 0

        for hunk in hunks:
            start_line = max(hunk["old_start"] - 1, 0)
            if start_line < cursor:
                raise ValueError("overlapping hunks detected")
            result.extend(source_lines[cursor:start_line])
            cursor = start_line

            for sign, text, has_newline in hunk["lines"]:
                line_with_nl = text + ("\n" if has_newline else "")

                if sign == " ":
                    if cursor >= len(source_lines):
                        raise ValueError("context exceeds file length")
                    if source_lines[cursor] != line_with_nl:
                        raise ValueError("context mismatch while applying patch")
                    result.append(source_lines[cursor])
                    cursor += 1
                elif sign == "-":
                    if cursor >= len(source_lines):
                        raise ValueError("deletion beyond end of file")
                    if source_lines[cursor] != line_with_nl:
                        raise ValueError("deletion mismatch while applying patch")
                    cursor += 1
                elif sign == "+":
                    result.append(line_with_nl)
                else:
                    raise ValueError(f"unsupported diff opcode: {sign}")

        result.extend(source_lines[cursor:])
        return "".join(result)


def _apply_unified_diff_stream(path: Path, hunks: List[Dict[str, Any]], dest: Path) -> None:
        with path.open('r', encoding='utf-8') as src, dest.open('w', encoding='utf-8') as dst:
            current_line = 1
            for hunk in hunks:
                target_line = max(hunk["old_start"], 1)
                while current_line < target_line:
                    line = src.readline()
                    if not line:
                        raise ValueError("context exceeds file length")
                    dst.write(line)
                    current_line += 1
                for sign, text, has_newline in hunk["lines"]:
                    line_with_nl = text + ("\n" if has_newline else "")
                    if sign == " ":
                        existing = src.readline()
                        if existing != line_with_nl:
                            raise ValueError("context mismatch while applying patch")
                        dst.write(existing)
                        current_line += 1
                    elif sign == "-":
                        existing = src.readline()
                        if existing != line_with_nl:
                            raise ValueError("deletion mismatch while applying patch")
                        current_line += 1
                    elif sign == "+":
                        dst.write(line_with_nl)
                    else:
                        raise ValueError(f"unsupported diff opcode: {sign}")
            shutil.copyfileobj(src, dst)


def _infer_unified_action(
    file_exists: bool,
    unified: Dict[str, Any],
) -> str:
    hunks = unified.get("hunks", [])
    has_additions = any(sign == "+" for h in hunks for sign, *_ in h["lines"])
    has_deletions = any(sign == "-" for h in hunks for sign, *_ in h["lines"])
    old_file = (unified.get("old_file") or "").lower()
    new_file = (unified.get("new_file") or "").lower()

    if not file_exists:
        if has_deletions and not has_additions:
            raise ValueError("cannot delete from non-existent file")
        return "add"
    if has_additions and has_deletions:
        return "update"
    if has_additions and not has_deletions:
        return "update"
    if not has_additions and has_deletions:
        if new_file.endswith("/dev/null"):
            return "delete"
        return "update"
    return "update"


def apply_patch_impl(input: Dict[str, Any]) -> str:
    file_path = input.get("file_path", "").strip()
    patch = input.get("patch", "")
    if not file_path or not patch:
        raise ValueError("missing 'file_path' or 'patch'")

    dry_run = bool(input.get("dry_run", False))

    target = Path(file_path)
    action, header_path = _parse_header(patch)
    unified = _parse_unified_diff(patch)

    rename_from: Optional[str] = None
    rename_to: Optional[str] = None
    if unified:
        old_header = unified.get("old_file")
        new_header = unified.get("new_file")
        if old_header and new_header and old_header not in {"/dev/null"} and new_header not in {"/dev/null"}:
            if _normalize_compare_path(old_header) != _normalize_compare_path(new_header):
                rename_from = old_header
                rename_to = new_header

    desired_action = (action or "Update").capitalize()

    # Reject binary patches up front
    binary_marker = _detect_binary_patch(patch)
    if binary_marker:
        return _build_error(desired_action, file_path, "binary patches are not supported", dry_run=dry_run)

    # Reject header mismatches to avoid accidental renames
    if header_path and _normalize_compare_path(header_path) != _normalize_compare_path(file_path):
        rename_hint = ""
        if rename_from and rename_to:
            rename_hint = (
                f" Detected rename from '{rename_from}' to '{rename_to}'. "
                "Run rename_file first, then re-apply the patch."
            )
        return _build_error(
            desired_action,
            file_path,
            f"patch header path '{header_path}' does not match file_path '{file_path}'.{rename_hint}",
            dry_run=dry_run,
        )

    # Prefer unified diff semantics when available
    if unified:
        file_exists = target.exists()
        inferred_action = action.lower() if action else _infer_unified_action(file_exists, unified)

        old_header = unified.get("old_file")
        new_header = unified.get("new_file")
        compare_target = _normalize_compare_path(file_path)
        for header_value in (old_header, new_header):
            if header_value in (None, "/dev/null"):
                continue
            if _normalize_compare_path(header_value) != compare_target:
                rename_hint = ""
                if rename_from and rename_to:
                    rename_hint = (
                        f" Detected rename from '{rename_from}' to '{rename_to}'. "
                        "Use rename_file before applying this patch."
                    )
                return _build_error(
                    inferred_action.capitalize(),
                    file_path,
                    f"unified diff path '{header_value}' does not match file_path '{file_path}'.{rename_hint}",
                    dry_run=dry_run,
                )

        if inferred_action == "delete":
            if dry_run:
                note = None if file_exists else "file did not exist"
                return _build_success("Delete", file_path, dry_run=True, note=note)
            try:
                target.unlink()
                return _build_success("Delete", file_path)
            except FileNotFoundError:
                return _build_success("Delete", file_path, note="file did not exist")
            except Exception as exc:
                return _build_error("Delete", file_path, str(exc), dry_run=dry_run)

        try:
            original = target.read_text(encoding="utf-8") if file_exists else ""
            updated = _apply_unified_diff(original, unified["hunks"])
            if dry_run:
                return _build_success(inferred_action.capitalize(), file_path, dry_run=True)
            _ensure_parent_dirs(target)
            if file_exists:
                temp_path = target.with_suffix(target.suffix + ".patch.tmp")
                _apply_unified_diff_stream(target, unified["hunks"], temp_path)
                temp_path.replace(target)
            else:
                target.write_text(updated, encoding="utf-8")
            return _build_success(inferred_action.capitalize(), file_path)
        except Exception as exc:
            message = str(exc)
            if isinstance(exc, ValueError):
                if "context mismatch" in message or "deletion mismatch" in message or "beyond end of file" in message:
                    message = (
                        f"{message}. The file content likely diverged from the patch. "
                        "Re-read the file or regenerate the diff after syncing."
                    )
                elif "overlapping hunks" in message:
                    message = f"{message}. Split the patch into non-overlapping hunks and retry."
            return _build_error("Update", file_path, message, dry_run=dry_run)

    if action.lower() == "delete":
        if dry_run:
            note = None if target.exists() else "file did not exist"
            return _build_success("Delete", file_path, dry_run=True, note=note)
        try:
            target.unlink()
            return _build_success("Delete", file_path)
        except FileNotFoundError:
            return _build_success("Delete", file_path, note="file did not exist")
        except Exception as exc:
            return _build_error("Delete", file_path, str(exc), dry_run=dry_run)

    if action.lower() == "add":
        try:
            content = _extract_add_content(patch)
            if dry_run:
                return _build_success("Add", file_path, dry_run=True)
            _ensure_parent_dirs(target)
            target.write_text(content, encoding="utf-8")
            return _build_success("Add", file_path)
        except Exception as exc:
            return _build_error("Add", file_path, str(exc), dry_run=dry_run)

    # Default to Update when header missing or 'Update'
    try:
        existing = target.read_text(encoding="utf-8") if target.exists() else ""

        replacements = _collect_line_replacements(patch)
        if replacements:
            new_content = existing
            for old_line, new_line in replacements:
                if old_line not in new_content:
                    raise ValueError(f"old line not found: {old_line!r}")
                new_content = new_content.replace(old_line, new_line, 1)
        else:
            new_content = _extract_add_content(patch)

        if dry_run:
            return _build_success("Update", file_path, dry_run=True)

        _ensure_parent_dirs(target)
        target.write_text(new_content, encoding="utf-8")
        return _build_success("Update", file_path)
    except Exception as exc:
        message = str(exc)
        if isinstance(exc, ValueError):
            if "old line not found" in message:
                message = (
                    f"{message}. The patch context does not match the current file; "
                    "ensure the file is up to date or regenerate the diff."
                )
        return _build_error("Update", file_path, message, dry_run=dry_run)
