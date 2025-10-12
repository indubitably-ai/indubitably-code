"""Execution policy helpers for tool sandboxing and approvals."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional, Sequence, Tuple


class SandboxPolicy(Enum):
    """Sandbox restriction levels."""

    NONE = "none"
    RESTRICTED = "restricted"
    STRICT = "strict"


class ApprovalPolicy(Enum):
    """When to request user approval."""

    NEVER = "never"
    ON_REQUEST = "on_request"
    ON_WRITE = "on_write"
    ALWAYS = "always"


@dataclass(frozen=True)
class ExecutionContext:
    """Context for tool execution with sandbox and approval policies."""

    cwd: Path
    sandbox_policy: SandboxPolicy
    approval_policy: ApprovalPolicy
    allowed_paths: Optional[Tuple[Path, ...]] = None
    blocked_commands: Optional[Tuple[str, ...]] = None
    timeout_seconds: Optional[float] = None

    def can_execute_command(self, command: str) -> tuple[bool, Optional[str]]:
        """Return whether *command* is permitted under sandbox rules."""

        text = (command or "").strip()
        if not text:
            return False, "Command must not be empty"

        if self.blocked_commands:
            for blocked in self.blocked_commands:
                if blocked and blocked in text:
                    return False, f"Command contains blocked pattern: {blocked}"

        if self.sandbox_policy == SandboxPolicy.STRICT:
            safe_commands = {"ls", "cat", "echo", "pwd", "grep"}
            first_token = text.split()[0]
            if first_token not in safe_commands:
                return False, f"Command '{first_token}' not allowed in strict mode"

        return True, None

    def can_write_path(self, path: Path) -> tuple[bool, Optional[str]]:
        """Return whether the agent may write to *path*."""

        target = path.resolve()

        if self.allowed_paths:
            allowed = False
            for candidate in self.allowed_paths:
                try:
                    target.relative_to(candidate.resolve())
                except ValueError:
                    continue
                else:
                    allowed = True
                    break
            if not allowed:
                return False, f"Path {target} not under allowed paths"

        system_paths = (Path("/etc"), Path("/sys"), Path("/proc"), Path("/dev"))
        for system_path in system_paths:
            try:
                target.relative_to(system_path)
            except ValueError:
                continue
            else:
                return False, f"Cannot write to system path {system_path}"

        return True, None

    def requires_approval(self, tool_name: str, *, is_write: bool) -> bool:
        """Return whether the tool invocation needs explicit approval."""

        if self.approval_policy == ApprovalPolicy.ALWAYS:
            return True
        if self.approval_policy == ApprovalPolicy.ON_WRITE:
            return is_write
        if self.approval_policy == ApprovalPolicy.ON_REQUEST:
            return False
        return False


__all__ = ["ApprovalPolicy", "ExecutionContext", "SandboxPolicy"]
