"""Helpers to summarize tool invocations for CLI and telemetry."""
from __future__ import annotations

from typing import Any, Iterable, List

_SUMMARY_KEYS: tuple[str, ...] = (
    "path",
    "file_path",
    "target",
    "destination",
    "query",
    "pattern",
    "command",
    "text",
    "prompt",
)


def truncate_text(value: Any, *, limit: int = 60) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    if limit < 4:
        return text[:limit]
    return text[: limit - 3] + "..."


def summarize_tool_payload(payload: Any, *, limit: int = 60) -> str:
    if isinstance(payload, dict):
        for key in _SUMMARY_KEYS:
            val = payload.get(key)
            if isinstance(val, (str, int, float)):
                return truncate_text(val, limit=limit)
        return ""
    if isinstance(payload, list):
        simple: List[str] = []
        for item in payload:
            if isinstance(item, (str, int, float, bool)):
                simple.append(truncate_text(item, limit=limit))
            if len(simple) >= 2:
                break
        return ", ".join(simple)
    if isinstance(payload, (str, int, float, bool)):
        return truncate_text(payload, limit=limit)
    return ""


def summarize_tool_call(name: str, payload: Any, *, limit: int = 60) -> str:
    base = name or "tool"
    summary = summarize_tool_payload(payload, limit=limit)
    return f"{base}({summary})" if summary else base


__all__ = ["truncate_text", "summarize_tool_payload", "summarize_tool_call"]
