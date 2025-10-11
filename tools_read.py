from __future__ import annotations

import os
from collections import deque
from typing import Any, Dict, Optional

from pydantic import ValidationError

from tools.schemas import ReadFileInput


def read_file_tool_def() -> dict:
    return {
        "name": "read_file",
        "description": (
            "Read a file's contents efficiently with optional byte or line ranges. "
            "If both byte and line ranges are provided, byte range takes precedence. "
            "Use for file contents. Not for directories."
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


def read_file_impl(input: Dict[str, Any]) -> str:
    try:
        params = ReadFileInput(**input)
    except ValidationError as exc:
        # Match legacy behaviour by surfacing ValueError with readable message
        messages = []
        for err in exc.errors():
            loc = ".".join(str(item) for item in err.get("loc", ())) or "input"
            messages.append(f"{loc}: {err.get('msg', 'invalid value')}")
        raise ValueError("; ".join(messages)) from exc

    path = params.path
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    if os.path.isdir(path):
        raise IsADirectoryError(path)

    encoding = params.encoding or "utf-8"
    errors = params.errors or "replace"

    if params.byte_offset is not None or params.byte_limit is not None:
        bo = params.byte_offset or 0
        bl = params.byte_limit
        return _read_bytes_range(path, bo, bl, encoding, errors)

    if params.tail_lines is not None:
        return _read_tail_lines(path, params.tail_lines, encoding, errors)

    if params.offset is not None or params.limit is not None:
        start = params.offset or 1
        lim = params.limit
        return _read_lines_range(path, start, lim, encoding, errors)

    return _read_full_text(path, encoding, errors)

