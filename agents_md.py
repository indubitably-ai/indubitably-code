"""Load Agents.md guidance for the prompt stack."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

DEFAULT_FILENAMES: Sequence[str] = ("AGENTS.md", "Agents.md", "agents.md")
MAX_FILE_BYTES = 200_000


@dataclass(frozen=True)
class AgentsMdDocument:
    """Materialised Agents.md guidance."""

    path: Path
    text: str

    def system_text(self) -> str:
        """Return the text to register as a system message."""

        return self.text


def load_agents_md(
    start_dir: Optional[Path] = None,
    *,
    filenames: Sequence[str] = DEFAULT_FILENAMES,
) -> Optional[AgentsMdDocument]:
    """Find and load an Agents.md document starting from *start_dir*.

    Walks up toward the repository root (detected via `.git`) until it finds a
    matching filename. Returns ``None`` when no readable file is present or if the
    file is empty.
    """

    base = (start_dir or Path.cwd()).resolve()
    for directory in _candidate_directories(base):
        for name in filenames:
            candidate = directory / name
            if not candidate.is_file():
                continue
            text = _read_agents_md(candidate)
            if text:
                return AgentsMdDocument(path=candidate, text=text)
    return None


def _candidate_directories(base: Path) -> Iterable[Path]:
    current = base
    seen: set[Path] = set()
    while current not in seen:
        seen.add(current)
        yield current
        if (current / ".git").exists():
            break
        if current.parent == current:
            break
        current = current.parent


def _read_agents_md(path: Path) -> str:
    data = path.read_bytes()
    if not data:
        return ""
    if len(data) > MAX_FILE_BYTES:
        data = data[:MAX_FILE_BYTES]
    text = data.decode("utf-8", errors="ignore").strip()
    return text


__all__ = ["AgentsMdDocument", "DEFAULT_FILENAMES", "MAX_FILE_BYTES", "load_agents_md"]
