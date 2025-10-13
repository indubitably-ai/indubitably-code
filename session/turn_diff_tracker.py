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
    conflicts: List[str] = field(default_factory=list)
    _undone: bool = field(default=False, init=False, repr=False)

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
        previous_edits = self.get_edits_for_path(resolved)
        if previous_edits:
            last_with_content = next(
                (ed for ed in reversed(previous_edits) if ed.new_content is not None),
                None,
            )
            if (
                last_with_content is not None
                and last_with_content.new_content is not None
                and old_content is not None
                and last_with_content.new_content != old_content
            ):
                self.conflicts.append(
                    f"{resolved}: prior new content diverges from current old content (tool={tool_name})"
                )

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

    def generate_conflict_report(self) -> Optional[str]:
        if not self.conflicts:
            return None
        lines = [f"Turn {self.turn_id} conflict warnings:"]
        lines.extend(f"  - {msg}" for msg in self.conflicts)
        return "\n".join(lines)

    def undo(self) -> List[str]:
        if self._undone:
            return []

        operations: List[str] = []

        for edit in reversed(self.edits):
            path = edit.path
            action = (edit.action or "").lower()

            if action in {"create", "add"} and edit.old_content is None:
                if path.exists():
                    path.unlink()
                    operations.append(f"removed {path}")
                continue

            if action == "delete":
                if edit.old_content is not None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(edit.old_content, encoding="utf-8")
                    operations.append(f"restored {path}")
                continue

            if action == "rename":
                dest_str = edit.new_content or ""
                if not dest_str:
                    continue
                candidates = []
                dest_candidate = Path(dest_str)
                candidates.append(dest_candidate)
                if not dest_candidate.is_absolute():
                    candidates.append((path.parent / dest_candidate).resolve())
                try:
                    candidates.append(dest_candidate.resolve())
                except FileNotFoundError:
                    pass
                moved = False
                for candidate in candidates:
                    try:
                        candidate_path = Path(candidate)
                        if candidate_path.exists():
                            candidate_path.rename(path)
                            operations.append(f"renamed {candidate_path} -> {path}")
                            moved = True
                            break
                    except Exception:
                        continue
                if not moved:
                    operations.append(f"rename undo failed for {path}")
                continue

            if edit.old_content is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(edit.old_content, encoding="utf-8")
                operations.append(f"reverted {path}")
            else:
                if path.exists():
                    path.unlink()
                    operations.append(f"removed {path}")

        self._undone = True
        return operations


__all__ = ["FileEdit", "TurnDiffTracker"]
