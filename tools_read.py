from typing import Dict, Any, Optional
from collections import deque
import os


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
    path = input.get("path", "")
    if not path:
        raise ValueError("missing 'path'")

    if not os.path.exists(path):
        raise FileNotFoundError(path)
    if os.path.isdir(path):
        raise IsADirectoryError(path)

    encoding = (input.get("encoding") or "utf-8").strip() or "utf-8"
    errors = (input.get("errors") or "replace").strip() or "replace"

    # Byte range takes precedence if provided
    byte_offset = input.get("byte_offset")
    byte_limit = input.get("byte_limit")
    if byte_offset is not None or byte_limit is not None:
        bo = int(byte_offset or 0)
        bl = int(byte_limit) if byte_limit is not None else None
        return _read_bytes_range(path, bo, bl, encoding, errors)

    # Tail lines next
    tail_lines = input.get("tail_lines")
    if tail_lines is not None:
        return _read_tail_lines(path, int(tail_lines), encoding, errors)

    # Line range
    offset = input.get("offset")
    limit = input.get("limit")
    if offset is not None or limit is not None:
        start = int(offset or 1)
        lim = int(limit) if limit is not None else None
        return _read_lines_range(path, start, lim, encoding, errors)

    # Full file
    return _read_full_text(path, encoding, errors)


