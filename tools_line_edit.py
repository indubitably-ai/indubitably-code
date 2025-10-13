from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from tools.handler import ToolOutput
from tools.schemas import LINE_EDIT_MODES, LineEditInput
from session.turn_diff_tracker import TurnDiffTracker

_LARGE_FILE_WARNING_LINES = 2000


def line_edit_tool_def() -> dict:
    return {
        "name": "line_edit",
        "description": (
            "Perform precise line edits in a text file. Supports inserting before/after a line, "
            "replacing a span, or deleting lines based on a 1-based line number or anchor text."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "path": {"type": "string", "description": "Path to the target text file."},
                "mode": {
                    "type": "string",
                    "enum": sorted(LINE_EDIT_MODES),
                    "description": "insert_before | insert_after | replace | delete",
                },
                "line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "1-based line number used to locate the edit position.",
                },
                "anchor": {
                    "type": "string",
                    "description": "Exact line contents to locate the edit position (ignored trailing newline).",
                },
                "occurrence": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Nth occurrence of the anchor to target (default 1).",
                },
                "line_count": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Number of lines to replace/delete (default 1).",
                },
                "text": {
                    "type": "string",
                    "description": "Replacement or insertion text (multi-line allowed).",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "When true, validate edits without modifying the file.",
                },
            },
            "required": ["path", "mode"],
        },
    }


def _normalize_text_block(text: Optional[str]) -> List[str]:
    if text is None:
        return []
    lines = text.splitlines(keepends=True)
    if not lines:
        return []
    if not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    return lines


def _read_lines(path: Path) -> List[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines(keepends=True)
    except FileNotFoundError as exc:
        raise FileNotFoundError(str(exc))


def _resolve_index(
    *,
    lines: Iterable[str],
    line_number: Optional[int],
    anchor: Optional[str],
    occurrence: int,
) -> tuple[int, int]:
    if line_number is not None and anchor is not None:
        raise ValueError("specify either 'line' or 'anchor', not both")
    if line_number is None and anchor is None:
        raise ValueError("either 'line' or 'anchor' is required")

    if line_number is not None:
        return line_number - 1, 0

    target = anchor or ""
    matches: List[tuple[int, int]] = []
    byte_offset = 0
    for idx, content in enumerate(lines):
        if content.rstrip("\n") == target:
            matches.append((idx, byte_offset))
        byte_offset += len(content)
    if len(matches) < occurrence:
        raise ValueError(f"anchor not found {occurrence} time(s)")
    return matches[occurrence - 1]



def _stream_line_edit(
    *,
    source: Path,
    dest: Path,
    insert_index: int,
    end_index: int,
    insert_block: List[str],
    mode: str,
) -> None:
    with source.open('r', encoding='utf-8') as src, dest.open('w', encoding='utf-8') as dst:
        for _ in range(insert_index):
            dst.write(src.readline())
        if mode in {"replace", "delete"}:
            for _ in range(end_index - insert_index):
                src.readline()
        for line in insert_block:
            dst.write(line)
        shutil.copyfileobj(src, dst)



def line_edit_impl(params: LineEditInput, tracker: Optional[TurnDiffTracker] = None) -> ToolOutput:
    path_value = params.path.strip()
    mode_value = params.mode

    target_path = Path(path_value)
    if not target_path.exists():
        return ToolOutput(content=path_value, success=False, metadata={"error_type": "not_found"})
    if not target_path.is_file():
        return ToolOutput(content=path_value, success=False, metadata={"error_type": "is_directory"})

    line_number = params.line
    anchor = params.anchor
    occurrence = params.occurrence
    line_count = params.line_count
    text_value = params.text
    dry_run = params.dry_run

    lines = _read_lines(target_path)
    original_text = "".join(lines)
    total_lines = len(lines)
    warning = None
    if total_lines >= _LARGE_FILE_WARNING_LINES:
        warning = f"file has {total_lines} lines; consider template_block for large edits"

    if line_number is not None:
        if mode_value == "insert_before":
            if line_number > total_lines + 1:
                return ToolOutput(content="line out of range", success=False, metadata={"error_type": "edit_error"})
        elif mode_value == "insert_after":
            if line_number > total_lines:
                return ToolOutput(content="line out of range", success=False, metadata={"error_type": "edit_error"})
        else:
            if line_number > total_lines:
                return ToolOutput(content="line out of range", success=False, metadata={"error_type": "edit_error"})

    try:
        index, byte_offset = _resolve_index(
            lines=lines,
            line_number=line_number,
            anchor=anchor,
            occurrence=occurrence,
        )
    except Exception as exc:
        return ToolOutput(content=str(exc), success=False, metadata={"error_type": "edit_error"})

    if mode_value == "insert_after":
        if index < len(lines):
            byte_offset += len(lines[index])
        index += 1

    if mode_value in {"replace", "delete"} and index >= total_lines:
        return ToolOutput(content="target line outside file range", success=False, metadata={"error_type": "edit_error"})

    if mode_value in {"replace", "delete"}:
        end_index = index + line_count
        if end_index > total_lines:
            return ToolOutput(content="line_count extends past end of file", success=False, metadata={"error_type": "edit_error"})
    else:
        end_index = index

    insert_block: List[str] = []
    if mode_value in {"insert_before", "insert_after", "replace"}:
        insert_block = _normalize_text_block(text_value)
        if not insert_block:
            return ToolOutput(content='text must contain at least one line; use "\\n" for a blank line', success=False, metadata={"error_type": "edit_error"})

    affected = line_count if mode_value in {"replace", "delete"} else len(insert_block)

    offset_start = byte_offset
    if mode_value in {"replace", "delete"}:
        offset_end = offset_start + sum(len(lines[i]) for i in range(index, end_index))
    else:
        offset_end = offset_start

    base_result: Dict[str, Any] = {
        "ok": True,
        "action": mode_value,
        "path": path_value,
        "line": index + 1,
        "lines_changed": affected,
        "total_lines": total_lines,
        "offset_start": offset_start,
        "offset_end": offset_end,
    }
    if warning:
        base_result["warning"] = warning
    if anchor is not None:
        base_result["anchor"] = anchor

    if dry_run:
        base_result["dry_run"] = True
        return ToolOutput(content=json.dumps(base_result), success=True)

    if tracker is not None:
        tracker.lock_file(target_path)
    try:
        temp_path = target_path.with_suffix(target_path.suffix + '.lineedit.tmp')
        _stream_line_edit(
            source=target_path,
            dest=temp_path,
            insert_index=index,
            end_index=end_index,
            insert_block=insert_block,
            mode=mode_value,
        )
        temp_path.replace(target_path)
    finally:
        if tracker is not None:
            tracker.unlock_file(target_path)

    if tracker is not None:
        try:
            updated_text = target_path.read_text(encoding="utf-8")
        except Exception:
            updated_text = ""
        line_range: Optional[tuple[int, int]] = None
        if mode_value in {"replace", "delete"}:
            line_range = (index + 1, end_index)
        tracker.record_edit(
            path=target_path,
            tool_name="line_edit",
            action=mode_value,
            old_content=original_text,
            new_content=updated_text,
            line_range=line_range,
        )

    return ToolOutput(content=json.dumps(base_result), success=True)



