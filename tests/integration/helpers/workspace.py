"""Temporary workspace utilities used by integration tests."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Tuple


@dataclass
class TempWorkspace:
    """Filesystem sandbox rooted at *root* with convenience helpers."""

    root: Path

    def path(self, *parts: str) -> Path:
        """Return an absolute path beneath the sandbox root."""
        return (self.root.joinpath(*parts)).resolve()

    def write(self, relative: str, content: str, *, encoding: str = "utf-8") -> Path:
        """Create or overwrite *relative* with *content*."""
        target = self.path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding=encoding)
        return target

    def read(self, relative: str, *, encoding: str = "utf-8") -> str:
        """Read and return the contents of *relative*."""
        return self.path(relative).read_text(encoding=encoding)

    def exists(self, relative: str) -> bool:
        """Return ``True`` if *relative* exists under the sandbox root."""
        return self.path(relative).exists()

    def listdir(self, relative: str = ".") -> Tuple[str, ...]:
        """Return directory entries beneath *relative* sorted by name."""
        directory = self.path(relative)
        return tuple(sorted(entry.name for entry in directory.iterdir()))


def create_workspace(base: Path) -> TempWorkspace:
    """Instantiate a :class:`TempWorkspace` rooted at *base* directory."""
    base.mkdir(parents=True, exist_ok=True)
    return TempWorkspace(root=base)


__all__ = ["TempWorkspace", "create_workspace"]
