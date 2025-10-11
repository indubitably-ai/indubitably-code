"""Utilities for formatting tool outputs with truncation safeguards."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final
import json

MODEL_FORMAT_MAX_BYTES: Final[int] = 10 * 1024  # 10 KiB
MODEL_FORMAT_MAX_LINES: Final[int] = 256
MODEL_FORMAT_HEAD_LINES: Final[int] = 128
MODEL_FORMAT_TAIL_LINES: Final[int] = 128
MODEL_FORMAT_HEAD_BYTES: Final[int] = 5 * 1024


@dataclass
class ExecOutput:
    """Structured output from command execution."""

    exit_code: int
    duration_seconds: float
    output: str
    timed_out: bool = False


def format_exec_output(output: ExecOutput) -> str:
    """Format execution output for model consumption with truncation."""

    content = output.output or ""
    if output.timed_out:
        content = f"command timed out after {output.duration_seconds:.1f}s\n{content}".rstrip("\n")
        content += "\n"

    lines = content.splitlines(keepends=True)
    total_lines = len(lines)

    if _within_limits(content, total_lines):
        return _format_output_json(output, content)

    truncated = _truncate_head_tail(content, lines, total_lines)
    summary = f"Total output lines: {total_lines}\n\n{truncated}"
    return _format_output_json(output, summary)


def _within_limits(content: str, total_lines: int) -> bool:
    return len(content.encode("utf-8")) <= MODEL_FORMAT_MAX_BYTES and total_lines <= MODEL_FORMAT_MAX_LINES


def _truncate_head_tail(content: str, lines: list[str], total_lines: int) -> str:
    head_lines = lines[:MODEL_FORMAT_HEAD_LINES]
    tail_lines = lines[-MODEL_FORMAT_TAIL_LINES:] if total_lines > MODEL_FORMAT_HEAD_LINES else []

    omitted = max(0, total_lines - len(head_lines) - len(tail_lines))

    head_text = "".join(head_lines)
    tail_text = "".join(tail_lines)
    marker = f"\n[... omitted {omitted} of {total_lines} lines ...]\n\n"

    head_trimmed = _trim_head_bytes(head_text, MODEL_FORMAT_HEAD_BYTES)
    result = head_trimmed + marker
    used_bytes = len(result.encode("utf-8"))

    remaining_budget = MODEL_FORMAT_MAX_BYTES - used_bytes
    if remaining_budget > 0 and tail_text:
        tail_trimmed = _trim_tail_bytes(tail_text, remaining_budget)
        result += tail_trimmed

    # Ensure final size is within budget (defensive)
    encoded = result.encode("utf-8")
    if len(encoded) > MODEL_FORMAT_MAX_BYTES:
        result = encoded[:MODEL_FORMAT_MAX_BYTES].decode("utf-8", errors="ignore")
    return result


def _trim_head_bytes(text: str, limit: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    trimmed = encoded[:limit]
    decoded = trimmed.decode("utf-8", errors="ignore")
    last_newline = decoded.rfind("\n")
    if last_newline != -1:
        return decoded[: last_newline + 1]
    return decoded


def _trim_tail_bytes(text: str, limit: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    trimmed = encoded[-limit:]
    decoded = trimmed.decode("utf-8", errors="ignore")
    first_newline = decoded.find("\n")
    if first_newline != -1 and first_newline + 1 < len(decoded):
        return decoded[first_newline + 1 :]
    return decoded


def _format_output_json(output: ExecOutput, content: str) -> str:
    payload = {
        "output": content,
        "metadata": {
            "exit_code": output.exit_code,
            "duration_seconds": round(output.duration_seconds, 1),
            "timed_out": output.timed_out,
        },
    }
    return json.dumps(payload, ensure_ascii=False)


__all__ = [
    "ExecOutput",
    "format_exec_output",
]
