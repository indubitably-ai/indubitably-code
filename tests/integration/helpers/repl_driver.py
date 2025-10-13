"""Utility helpers for exercising the interactive REPL in integration tests."""
from __future__ import annotations

import io
import sys
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

from agent import Tool, run_agent


@dataclass
class ReplResult:
    """Captured output from a REPL execution."""

    stdout: str
    stderr: str
    transcript_path: Path | None


class ReplDriver:
    """Drive ``run_agent`` with scripted user input inside tests."""

    def __init__(self) -> None:
        self._stack = ExitStack()
        self._original_stdin = None

    def run(
        self,
        *,
        tools: Sequence[Tool],
        user_commands: Iterable[str],
        transcript_path: Path | None = None,
        use_color: bool = False,
        debug_tool_use: bool = False,
        tool_debug_log: Path | None = None,
    ) -> ReplResult:
        """Execute ``run_agent`` with scripted commands and capture output."""

        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()

        input_lines = list(user_commands)
        if not input_lines or input_lines[-1] != "":
            input_lines.append("")  # Ensure EOF terminates session

        class _Stub:
            def __init__(self, lines: List[str]) -> None:
                self._lines = list(lines)

            def readline(self) -> str:
                return self._lines.pop(0) if self._lines else ""

            def isatty(self) -> bool:  # pragma: no cover - defensive
                return False

        stub = _Stub([line if line.endswith("\n") else f"{line}\n" for line in input_lines])

        self._stack.enter_context(redirect_stdout(stdout_buffer))
        self._stack.enter_context(redirect_stderr(stderr_buffer))
        self._original_stdin = sys.stdin
        sys.stdin = stub  # type: ignore[assignment]

        try:
            run_agent(
                list(tools),
                use_color=use_color,
                transcript_path=str(transcript_path) if transcript_path else None,
                debug_tool_use=debug_tool_use,
                tool_debug_log_path=str(tool_debug_log) if tool_debug_log else None,
            )
        finally:
            sys.stdin = self._original_stdin  # type: ignore[assignment]
            self._stack.close()

        return ReplResult(
            stdout=stdout_buffer.getvalue(),
            stderr=stderr_buffer.getvalue(),
            transcript_path=transcript_path,
        )


__all__ = ["ReplDriver", "ReplResult"]
