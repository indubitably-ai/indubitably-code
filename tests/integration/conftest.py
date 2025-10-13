"""Integration test fixtures."""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

from .helpers import TempWorkspace, create_workspace


@pytest.fixture
def integration_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TempWorkspace]:
    """Provide an isolated workspace and chdir into it for the duration of a test."""

    workspace = create_workspace(tmp_path / "workspace")
    monkeypatch.chdir(workspace.root)
    yield workspace


@pytest.fixture
def fake_figlet(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the banner font renderer with a deterministic stub."""

    class _Figlet:
        def __init__(self, font: str = "standard") -> None:
            self.font = font

        def renderText(self, text: str) -> str:
            return f"{text}\n"

    monkeypatch.setattr("agent.Figlet", lambda font="standard": _Figlet(font))
