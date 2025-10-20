from __future__ import annotations

import os
from collections import deque
from typing import Any, Dict, Optional

from tools.handler import ToolOutput
from tools.schemas import ReadFileInput


def read_file_tool_def() -> dict:
    return {
        "name": "read_file",
        "description": (
            "Retrieve text from a file with support for slices so agents can avoid loading huge blobs. Provide `path` (absolute or relative), optionally specify `encoding`/`errors` to control decoding, "
            "and choose one of several range modes: `byte_offset` + `byte_limit` reads a byte slice, `offset` + `limit` streams a line window, and `tail_lines` returns the last N lines. When multiple range parameters are set, "
            "byte ranges take precedence, mirroring Anthropic tool conventions. The JSON response includes the extracted content, encoding used, and path for traceability. Example: to inspect part of a migration file, call read_file with path='migrations/2025.sql', offset=50, limit=40. "
            "Avoid using this tool on directories (it will fail), for binary data that should be handled via base64 attachments, or when you need structured parsing—follow up with domain-specific logic after reading the text instead."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative or absolute path to a file.",
                },
                "encoding": {
                    "type": "string",
                    "description": "Text encoding (default utf-8).",
                    "default": "utf-8",
                },
                "errors": {
                    "type": "string",
                    "description": "Decoding error policy: strict|ignore|replace (default replace).",
                    "default": "replace",
                },
                "byte_offset": {
                    "type": "integer",
                    "description": "Start reading at this byte offset (>=0).",
                    "minimum": 0,
                },
                "byte_limit": {
                    "type": "integer",
                    "description": "Maximum number of bytes to read.",
                    "minimum": 1,
                },
                "offset": {
                    "type": "integer",
                    "description": "1-based line start (default 1).",
                    "minimum": 1,
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of lines to read from offset.",
                    "minimum": 1,
                },
                "tail_lines": {
                    "type": "integer",
                    "description": "Return last N lines efficiently.",
                    "minimum": 1,
                },
            },
            "required": ["path"],
        },
    }


def _read_full_text(path: str, encoding: str, errors: str) -> str:
    with open(path, "rb") as f:
        data = f.read()
    return data.decode(encoding, errors=errors)


def _read_bytes_range(path: str, byte_offset: int, byte_limit: Optional[int], encoding: str, errors: str) -> str:
    with open(path, "rb") as f:
        if byte_offset:
            f.seek(byte_offset)
        data = f.read(byte_limit) if byte_limit is not None else f.read()
    return data.decode(encoding, errors=errors)


def _read_lines_range(path: str, offset: int, limit: Optional[int], encoding: str, errors: str) -> str:
    # Stream and slice by line to avoid loading the full file
    start_line = max(1, offset)
    num_needed = None if limit is None else max(0, limit)

    out_lines = []
    with open(path, "r", encoding=encoding, errors=errors) as f:
        for idx, line in enumerate(f, start=1):
            if idx < start_line:
                continue
            out_lines.append(line.rstrip("\n"))
            if num_needed is not None:
                num_needed -= 1
                if num_needed <= 0:
                    break
    return "\n".join(out_lines)


def _read_tail_lines(path: str, tail_lines: int, encoding: str, errors: str) -> str:
    if tail_lines <= 0:
        return ""
    dq = deque(maxlen=tail_lines)
    with open(path, "r", encoding=encoding, errors=errors) as f:
        for line in f:
            dq.append(line.rstrip("\n"))
    return "\n".join(dq)


def read_file_impl(params: ReadFileInput) -> ToolOutput:
    path = params.path
    try:
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        if os.path.isdir(path):
            raise IsADirectoryError(path)

        encoding = params.encoding or "utf-8"
        errors = params.errors or "replace"

        if params.byte_offset is not None or params.byte_limit is not None:
            bo = params.byte_offset or 0
            bl = params.byte_limit
            content = _read_bytes_range(path, bo, bl, encoding, errors)
        elif params.tail_lines is not None:
            content = _read_tail_lines(path, params.tail_lines, encoding, errors)
        elif params.offset is not None or params.limit is not None:
            start = params.offset or 1
            lim = params.limit
            content = _read_lines_range(path, start, lim, encoding, errors)
        else:
            content = _read_full_text(path, encoding, errors)

        import json as _json
        return ToolOutput(
            content=_json.dumps({
                "content": content,
                "path": path,
                "encoding": encoding,
            }),
            success=True,
        )
    except FileNotFoundError as exc:
        return ToolOutput(content=f"File not found: {exc}", success=False, metadata={"error_type": "not_found"})
    except IsADirectoryError as exc:
        return ToolOutput(content=f"Path is a directory: {exc}", success=False, metadata={"error_type": "is_directory"})
    except Exception as exc:
        return ToolOutput(content=f"Read failed: {exc}", success=False, metadata={"error_type": "io_error"})
