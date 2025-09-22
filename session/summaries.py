"""Rule-based summarisation helpers for compaction."""
from __future__ import annotations

import re
from typing import Iterable, List, Sequence

from .history import MessageRecord

_KEYWORD_MAP = {
    "goals": ("goal", "objective", "aim"),
    "decisions": ("decide", "decision", "chose", "selected"),
    "constraints": ("constraint", "must", "require", "limit", "blocked"),
    "todos": ("todo", "follow up", "pending", "next step"),
    "apis": ("api", "endpoint", "request", "http"),
}

_FILE_RE = re.compile(r"[\w\-/]+\.[\w]+")
_URL_RE = re.compile(r"https?://[^\s]+")


def summarize_conversation(records: Iterable[MessageRecord]) -> str:
    sections = {
        "goals": [],
        "decisions": [],
        "constraints": [],
        "files": [],
        "apis": [],
        "todos": [],
    }

    seen = {key: set() for key in sections}

    def _record(section: str, value: str) -> None:
        value = value.strip()
        if not value:
            return
        if value.lower() in seen[section]:
            return
        sections[section].append(value)
        seen[section].add(value.lower())

    fallback_lines: List[str] = []

    for record in records:
        for fragment in record.text_fragments():
            lines = [line.strip() for line in fragment.splitlines() if line.strip()]
            for line in lines:
                lower = line.lower()
                matched_section = False
                for section, keywords in _KEYWORD_MAP.items():
                    if any(keyword in lower for keyword in keywords):
                        _record(section, line)
                        matched_section = True
                        break
                file_match = _FILE_RE.search(line)
                if file_match:
                    _record("files", file_match.group())
                    matched_section = True
                if _URL_RE.search(line):
                    _record("apis", line)
                    matched_section = True
                if not matched_section:
                    fallback_lines.append(line)

    if not any(sections.values()):
        fallback = _summarize_freeform(fallback_lines)
        return fallback or "No major updates; older conversation compacted."

    parts: List[str] = []
    order: Sequence[tuple[str, str]] = (
        ("goals", "Goals"),
        ("decisions", "Decisions"),
        ("constraints", "Constraints"),
        ("files", "Files"),
        ("apis", "APIs"),
        ("todos", "Open TODOs"),
    )
    for section, title in order:
        items = sections[section]
        if not items:
            continue
        sample = items[:5]
        parts.append(title + ":")
        parts.extend("- " + item for item in sample)

    return "\n".join(parts)


def summarize_tool_output(text: str, *, max_lines: int = 20) -> str:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if len(lines) <= max_lines:
        return "\n".join(lines)
    head = lines[: max_lines // 2]
    tail = lines[-max_lines // 2 :]
    return "\n".join(head + ["...", "(truncated)"] + tail)


def _summarize_freeform(lines: List[str], *, limit: int = 8) -> str:
    if not lines:
        return "No major updates; older conversation compacted."
    deduped: List[str] = []
    seen = set()
    for line in lines:
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(line)
        if len(deduped) >= limit:
            break
    return "Older conversation summary:\n" + "\n".join("- " + line for line in deduped)


__all__ = ["summarize_conversation", "summarize_tool_output"]
