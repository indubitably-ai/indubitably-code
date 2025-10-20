from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from pydantic import ValidationError

from tools.handler import ToolOutput
from tools.schemas import TEMPLATE_MODES, TemplateBlockInput
from session.turn_diff_tracker import TurnDiffTracker


_MODE_INSERT_BEFORE = "insert_before"
_MODE_INSERT_AFTER = "insert_after"
_MODE_REPLACE = "replace_block"
_ALLOWED_MODES = TEMPLATE_MODES


_LARGE_FILE_WARNING_LINES = 2000


_STREAM_BUFFER_SIZE = 8192


@dataclass(frozen=True)
class TemplateCommand:
    path: Path
    mode: str
    anchor: str
    occurrence: int
    template: str
    expected_block: Optional[str]
    dry_run: bool


def template_block_tool_def() -> dict:
    return {
        "name": "template_block",
        "description": (
            "Insert or replace multi-line text blocks relative to an anchor string, ideal for structured sections like config stanzas or README snippets. Supply `path` to a text file, "
            "choose a `mode` (insert_before, insert_after, replace_block), and provide an exact `anchor` along with `occurrence` to disambiguate repeated blocks. The `template` field holds the new block; when replacing you must also pass `expected_block` so the tool verifies "
            "the existing content before rewriting. `dry_run=true` returns JSON describing anchor positions, byte offsets, and warnings (e.g., large file hints) without modifying disk, enabling agents to validate context first. Example: to append a new item to a markdown list, call template_block with mode='insert_after', anchor='## Features', template='- New bullet\n'. "
            "Avoid using this tool when you need multiple disjoint updates in one call (prefer apply_patch) or when the anchor text is unstable across versions—fetch the latest file with read_file first."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "path": {"type": "string", "description": "Target text file."},
                "mode": {
                    "type": "string",
                    "enum": sorted(_ALLOWED_MODES),
                    "description": "insert_before | insert_after | replace_block",
                },
                "anchor": {
                    "type": "string",
                    "description": "Anchor text used to locate the insertion/replacement point (exact match).",
                },
                "occurrence": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Nth occurrence of the anchor to target (default 1).",
                },
                "template": {
                    "type": "string",
                    "description": "Multi-line block to insert or use as replacement.",
                },
                "expected_block": {
                    "type": "string",
                    "description": "Existing block that must match before replacement (only for replace_block).",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "When true, validate and report locations without writing changes (default false).",
                },
            },
            "required": ["path", "mode", "anchor", "template"],
        },
    }


def _normalize_lines(text: str) -> List[str]:
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    if not lines:
        lines = ["\n"]
    return lines


def _locate_anchor(lines: List[str], anchor: str, occurrence: int) -> tuple[int, int]:
    anchor_lines = anchor.splitlines()
    if not anchor_lines:
        raise ValueError("anchor must contain text")

    normalized_anchor = [ln.rstrip("\n") for ln in anchor_lines]
    prefix: List[int] = [0]
    for line in lines:
        prefix.append(prefix[-1] + len(line))

    matches: List[tuple[int, int]] = []
    for idx in range(len(lines)):
        if idx + len(normalized_anchor) > len(lines):
            break
        segment = lines[idx: idx + len(normalized_anchor)]
        if [ln.rstrip("\n") for ln in segment] == normalized_anchor:
            matches.append((idx, prefix[idx]))
    if len(matches) < occurrence:
        raise ValueError("anchor not found at requested occurrence")
    return matches[occurrence - 1]


def _command_from_model(params: TemplateBlockInput) -> TemplateCommand:
    return TemplateCommand(
        path=Path(params.path.strip()),
        mode=params.mode,
        anchor=params.anchor,
        occurrence=params.occurrence,
        template=params.template,
        expected_block=params.expected_block,
        dry_run=params.dry_run,
    )


def _stream_apply_template(
    *,
    source: Path,
    dest: Path,
    insert_index: int,
    template_lines: List[str],
    replace_count: int,
) -> None:
    with source.open('r', encoding='utf-8') as src, dest.open('w', encoding='utf-8') as dst:
        for _ in range(insert_index):
            dst.write(src.readline())
        if replace_count:
            for _ in range(replace_count):
                src.readline()
        for line in template_lines:
            dst.write(line)
        shutil.copyfileobj(src, dst)



def template_block_impl(params: TemplateBlockInput, tracker: Optional[TurnDiffTracker] = None) -> ToolOutput:
    try:
        command = _command_from_model(params)
    except Exception as exc:
        return ToolOutput(content=str(exc), success=False, metadata={"error_type": "validation"})

    if not command.path.exists():
        return ToolOutput(content=str(command.path), success=False, metadata={"error_type": "not_found"})
    if not command.path.is_file():
        return ToolOutput(content=str(command.path), success=False, metadata={"error_type": "is_directory"})

    lines = command.path.read_text(encoding='utf-8').splitlines(keepends=True)
    original_text = "".join(lines)
    total_lines = len(lines)
    warning = None
    if total_lines >= _LARGE_FILE_WARNING_LINES:
        warning = f"file has {total_lines} lines; consider template_block dry_run before committing"

    try:
        anchor_index, byte_offset = _locate_anchor(lines, command.anchor, command.occurrence)
    except ValueError as exc:
        return ToolOutput(content=json.dumps({
            "ok": False,
            "action": command.mode,
            "path": str(command.path),
            "error": str(exc),
            "total_lines": total_lines,
        }), success=False, metadata={"error_type": "anchor_not_found"})

    anchor_lines = command.anchor.splitlines()
    insert_index = anchor_index
    if command.mode == _MODE_INSERT_AFTER:
        insert_index = anchor_index + len(anchor_lines)
        byte_offset += sum(len(lines[anchor_index + i]) for i in range(len(anchor_lines)))

    template_lines = _normalize_lines(command.template)

    offset_start = byte_offset
    if command.mode == _MODE_REPLACE:
        expected = command.expected_block
        if expected is None:
            return ToolOutput(content=json.dumps({
                "ok": False,
                "action": command.mode,
                "path": str(command.path),
                "error": "expected_block is required for replace_block mode",
            }), success=False, metadata={"error_type": "validation"})
        expected_lines = _normalize_lines(expected)
        segment = lines[insert_index: insert_index + len(expected_lines)]
        if [ln.rstrip("\n") for ln in segment] != [ln.rstrip("\n") for ln in expected_lines]:
            return ToolOutput(content=json.dumps({
                "ok": False,
                "action": command.mode,
                "path": str(command.path),
                "error": "existing block does not match expected_block",
            }), success=False, metadata={"error_type": "mismatch"})
        replace_count = len(expected_lines)
        offset_end = offset_start + sum(len(lines[insert_index + i]) for i in range(replace_count))
    else:
        replace_count = 0
        offset_end = offset_start

    response: Dict[str, Any] = {
        "ok": True,
        "action": command.mode,
        "path": str(command.path),
        "anchor_occurrence": command.occurrence,
        "target_line": insert_index + 1,
        "template_line_count": len(template_lines),
        "total_lines": total_lines,
        "offset_start": offset_start,
        "offset_end": offset_end,
    }
    if warning:
        response["warning"] = warning

    if command.dry_run:
        response["dry_run"] = True
        return ToolOutput(content=json.dumps(response), success=True)

    if tracker is not None:
        tracker.lock_file(command.path)
    try:
        temp_path = command.path.with_suffix(command.path.suffix + '.tmp-template')
        _stream_apply_template(
            source=command.path,
            dest=temp_path,
            insert_index=insert_index,
            template_lines=template_lines,
            replace_count=replace_count,
        )
        temp_path.replace(command.path)
        if tracker is not None:
            try:
                updated_text = command.path.read_text(encoding='utf-8')
            except Exception:
                updated_text = original_text
            line_range = (insert_index + 1, insert_index + max(1, len(template_lines)))
            tracker.record_edit(
                path=command.path,
                tool_name="template_block",
                action=command.mode,
                old_content=original_text,
                new_content=updated_text,
                line_range=line_range,
            )
    finally:
        if tracker is not None:
            tracker.unlock_file(command.path)
    response["lines_changed"] = len(template_lines)
    return ToolOutput(content=json.dumps(response), success=True)
