"""Utilities for loading headless agent configuration files."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Set


@dataclass(frozen=True)
class RunnerConfig:
    max_turns: Optional[int] = None
    exit_on_tool_error: Optional[bool] = None
    dry_run: Optional[bool] = None
    allowed_tools: Optional[Set[str]] = None
    blocked_tools: Optional[Set[str]] = None
    audit_log_path: Optional[Path] = None
    changes_log_path: Optional[Path] = None


def load_runner_config(path: Path) -> RunnerConfig:
    if not path.exists():
        raise FileNotFoundError(path)

    with path.open("rb") as fh:
        data = tomllib.load(fh)

    runner_section = data.get("runner", {})
    if not isinstance(runner_section, dict):
        raise ValueError("[runner] section must be a table")

    base_dir = path.parent

    def _to_set(value: Optional[object]) -> Optional[Set[str]]:
        if value is None:
            return None
        if isinstance(value, str):
            entries = [value]
        elif isinstance(value, (list, tuple, set)):
            entries = value
        else:
            raise ValueError("tool lists must be strings or arrays of strings")
        cleaned = {str(item).strip() for item in entries if str(item).strip()}
        return cleaned or None

    def _to_path(value: Optional[object]) -> Optional[Path]:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("paths must be strings")
        return (base_dir / value).resolve()

    def _to_bool(value: Optional[object]) -> Optional[bool]:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        raise ValueError("boolean fields accept only true/false")

    def _to_int(value: Optional[object]) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        raise ValueError("numeric fields accept integers")

    return RunnerConfig(
        max_turns=_to_int(runner_section.get("max_turns")),
        exit_on_tool_error=_to_bool(runner_section.get("exit_on_tool_error")),
        dry_run=_to_bool(runner_section.get("dry_run")),
        allowed_tools=_to_set(runner_section.get("allowed_tools")),
        blocked_tools=_to_set(runner_section.get("blocked_tools")) or None,
        audit_log_path=_to_path(runner_section.get("audit_log")),
        changes_log_path=_to_path(runner_section.get("changes_log")),
    )


__all__ = ["RunnerConfig", "load_runner_config"]
