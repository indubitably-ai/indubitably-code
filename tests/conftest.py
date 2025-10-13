"""Shared pytest fixtures for the indubitably-code test suite."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from types import ModuleType
from typing import Any, Iterable, Tuple, Union

import pytest

from tests.mocking import MockAnthropic


ModuleRef = Union[str, Tuple[ModuleType, str]]


@dataclass
class AnthropicMockHandle:
    """Helper that patches modules to return a shared ``MockAnthropic`` instance."""

    client: MockAnthropic
    monkeypatch: Any

    def patch(self, *targets: ModuleRef) -> MockAnthropic:
        """Patch provided module attribute paths to return the same client.

        ``targets`` accepts either dotted string paths (e.g. ``"agent.Anthropic"``)
        or ``(module, attr_name)`` tuples. When no targets are supplied the default
        is to patch the interactive and headless runners.
        """
        if not targets:
            targets = ("agent.Anthropic", "agent_runner.Anthropic")

        for target in targets:
            if isinstance(target, str):
                self.monkeypatch.setattr(target, lambda client=self.client: client)
            else:
                module, attr = target
                self.monkeypatch.setattr(module, attr, lambda client=self.client: client)
        return self.client


@pytest.fixture
def anthropic_mock(monkeypatch) -> AnthropicMockHandle:
    """Provide a ``MockAnthropic`` instance with convenient patching helpers."""
    client = MockAnthropic()
    return AnthropicMockHandle(client=client, monkeypatch=monkeypatch)


@pytest.fixture
def stdin_stub(monkeypatch):
    """Patch ``sys.stdin`` with a simple line-based stub."""

    def factory(*lines: str):
        class _Stub:
            def __init__(self, values: Iterable[str]):
                self._values = list(values)

            def readline(self) -> str:
                return self._values.pop(0) if self._values else ""

        stub = _Stub(lines)
        monkeypatch.setattr(sys, "stdin", stub)
        return stub

    return factory
