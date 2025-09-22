"""Slash command handling for interactive sessions."""
from __future__ import annotations

from typing import Optional

from session import ContextSession


def handle_slash_command(line: str, session: ContextSession) -> tuple[bool, str]:
    """Handle slash commands; return (handled, response_message)."""

    line = line.strip()
    if not line.startswith("/"):
        return False, ""
    parts = line[1:].split()
    if not parts:
        return False, ""
    command = parts[0].lower()
    args = parts[1:]

    if command == "compact":
        status = session.force_compact()
        if not status.triggered:
            return True, "Compaction skipped; nothing to summarize."
        summary = status.summary or "<no summary>"
        usage = f"tokens {status.total_tokens}/{status.window_tokens}"
        return True, f"Compaction complete ({usage}).\n{summary}"

    if command == "status":
        report = session.status()
        pins = report.get("pins", [])
        pins_lines = [f"  - {pin['id']}: {pin['text']}" for pin in pins] or ["  <none>"]
        telemetry = report.get("telemetry", {})
        lines = [
            f"Tokens: {report['tokens']}/{report['window']} ({report['usage_pct']}%)",
            f"Auto-compaction: {'on' if report['auto_compact'] else 'off'}",
            f"Keep last turns: {report['keep_last_turns']}",
            "Pins:",
            *pins_lines,
            f"Telemetry: {telemetry}",
        ]
        return True, "\n".join(lines)

    if command == "config" and args:
        sub = args[0].lower()
        if sub == "set" and len(args) >= 2:
            assignment = " ".join(args[1:])
            if "=" not in assignment:
                return True, "Usage: /config set group.field=value"
            key, value = assignment.split("=", 1)
            try:
                session.update_setting(key.strip(), value.strip())
            except Exception as exc:  # pragma: no cover - user feedback path
                return True, f"Failed to update setting: {exc}"
            return True, f"Updated setting {key.strip()} to {value.strip()}"
        return True, "Usage: /config set group.field=value"

    if command == "pin" and args:
        sub = args[0].lower()
        if sub == "add" and len(args) >= 2:
            try:
                ttl_seconds, text = _parse_pin_args(args[1:])
                pin = session.add_pin(text, ttl_seconds=ttl_seconds)
            except Exception as exc:  # pragma: no cover - user feedback path
                return True, f"Failed to add pin: {exc}"
            ttl_str = f" (ttl={ttl_seconds}s)" if ttl_seconds else ""
            return True, f"Pinned {pin.identifier}{ttl_str}"
        return True, "Usage: /pin add [--ttl=seconds] text"

    if command == "unpin" and args:
        identifier = args[0]
        if session.remove_pin(identifier):
            return True, f"Removed pin {identifier}"
        return True, f"Pin {identifier} not found"

    return True, "Unknown command"


def _parse_pin_args(args: list[str]) -> tuple[Optional[int], str]:
    ttl = None
    text_parts: list[str] = []
    for token in args:
        if token.startswith("--ttl="):
            try:
                ttl = int(token.split("=", 1)[1])
            except ValueError:
                raise ValueError("TTL must be an integer number of seconds")
        else:
            text_parts.append(token)
    text = " ".join(text_parts).strip()
    if not text:
        raise ValueError("Pin text required")
    return ttl, text


__all__ = ["handle_slash_command"]
