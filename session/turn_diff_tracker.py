"""Per-turn tracking of filesystem edits."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import difflib


@dataclass
class FileEdit:
    """Represents a single file mutation during a turn."""

    path: Path
    tool_name: str
    timestamp: datetime
    action: str
    old_content: Optional[str] = None
    new_content: Optional[str] = None
    line_range: Optional[Tuple[int, int]] = None


@dataclass
class TurnDiffTracker:
    """Accumulates file edits performed within a single turn."""

    turn_id: int
    edits: List[FileEdit] = field(default_factory=list)
    _edited_paths: Set[Path] = field(default_factory=set, init=False, repr=False)
    _locked_paths: Set[Path] = field(default_factory=set, init=False, repr=False)

    def record_edit(
        self,
        *,
        path: str | Path,
        tool_name: str,
        action: str,
        old_content: Optional[str] = None,
        new_content: Optional[str] = None,
        line_range: Optional[Tuple[int, int]] = None,
    ) -> None:
        """Record an edit made by a tool."""
        resolved = Path(path).resolve()
        edit = FileEdit(
            path=resolved,
            tool_name=tool_name,
            timestamp=datetime.now(),
            action=action,
            old_content=old_content,
            new_content=new_content,
            line_range=line_range,
        )
        self.edits.append(edit)
        self._edited_paths.add(resolved)

    def lock_file(self, path: str | Path) -> None:
        """Lock a file to guard against concurrent writes."""
        resolved = Path(path).resolve()
        if resolved in self._locked_paths:
            raise ValueError(f"File {resolved} is already locked")
        self._locked_paths.add(resolved)

    def unlock_file(self, path: str | Path) -> None:
        """Release a file lock."""
        resolved = Path(path).resolve()
        self._locked_paths.discard(resolved)

    def get_edits_for_path(self, path: str | Path) -> List[FileEdit]:
        resolved = Path(path).resolve()
        return [edit for edit in self.edits if edit.path == resolved]

    def generate_summary(self) -> str:
        if not self.edits:
            return "No files modified this turn."

        grouped: Dict[Path, List[FileEdit]] = {}
        for edit in self.edits:
            grouped.setdefault(edit.path, []).append(edit)

        lines = [f"Turn {self.turn_id} modifications:"]
        for path in sorted(grouped):
            actions = ", ".join(e.action for e in grouped[path])
            tools = ", ".join(sorted({e.tool_name for e in grouped[path]}))
            lines.append(f"  {path}: {actions} (via {tools})")
        return "\n".join(lines)

    def generate_unified_diff(self) -> Optional[str]:
        diffs: List[str] = []
        for path in sorted(self._edited_paths):
            path_edits = self.get_edits_for_path(path)
            if not path_edits:
                continue

            old_content: Optional[str] = None
            new_content: Optional[str] = None
            for edit in path_edits:
                if old_content is None and edit.old_content is not None:
                    old_content = edit.old_content
                if edit.new_content is not None:
                    new_content = edit.new_content

            if old_content is None or new_content is None:
                continue

            diff = difflib.unified_diff(
                old_content.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                lineterm="",
            )
            diffs.append("".join(diff))

        return "\n".join(diff for diff in diffs if diff) or None


__all__ = ["FileEdit", "TurnDiffTracker"]
