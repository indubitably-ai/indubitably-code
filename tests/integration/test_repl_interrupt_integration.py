"""Integration test ensuring REPL handles ESC interrupts gracefully."""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout, redirect_stderr

from agent import run_agent


def test_repl_interrupt(monkeypatch, fake_figlet) -> None:
    outputs = io.StringIO()
    errors = io.StringIO()

    lines = iter([
        "Hello\n",
        "\u001b",  # simulate ESC interrupt
        "",
    ])

    class _Stub:
        def readline(self):
            try:
                value = next(lines)
            except StopIteration:
                return ""
            return value

        def isatty(self) -> bool:
            return True

    stub = _Stub()
    monkeypatch.setattr(sys, "stdin", stub)

    with redirect_stdout(outputs), redirect_stderr(errors):
        run_agent([], use_color=False)

    captured = outputs.getvalue()
    assert captured.count('Quit') >= 2

