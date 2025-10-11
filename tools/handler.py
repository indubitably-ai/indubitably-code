"""Core tool handler protocol and supporting data structures."""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Protocol

from .payload import ToolPayload


class ToolKind(Enum):
    """Types of tools supported by the harness."""

    FUNCTION = "function"
    UNIFIED_EXEC = "unified_exec"
    MCP = "mcp"
    CUSTOM = "custom"


@dataclass
class ToolInvocation:
    """Context for a single tool invocation."""

    session: Any
    turn_context: Any
    tracker: Any
    sub_id: str
    call_id: str
    tool_name: str
    payload: ToolPayload


@dataclass
class ToolOutput:
    """Result of tool execution."""

    content: str
    success: bool
    metadata: Dict[str, Any] | None = None

    def log_preview(self, max_bytes: int = 2048, max_lines: int = 64) -> str:
        """Return a truncated preview string suitable for logging."""
        content = self.content or ""
        if len(content) <= max_bytes and content.count("\n") < max_lines:
            return content

        lines = content.splitlines()
        preview_lines = lines[:max_lines]
        preview = "\n".join(preview_lines)
        if len(preview) > max_bytes:
            preview = preview[:max_bytes]
        if len(preview) < len(content):
            preview += "\n[... truncated for telemetry ...]"
        return preview


class ToolHandler(Protocol):
    """Protocol describing tool handler implementations."""

    @property
    def kind(self) -> ToolKind:
        ...

    def matches_kind(self, payload: ToolPayload) -> bool:
        ...

    async def handle(self, invocation: ToolInvocation) -> ToolOutput:
        ...


async def execute_handler(handler: ToolHandler, invocation: ToolInvocation) -> ToolOutput:
    """Execute a handler and record telemetry on the context if available."""
    start = time.time()
    try:
        result = await handler.handle(invocation)
        success = result.success
        error: str | None = None
    except Exception as exc:  # pragma: no cover - defensive envelope
        success = False
        error = str(exc)
        result = ToolOutput(content=f"tool execution failed: {exc}", success=False)
    finally:
        duration = time.time() - start
        telemetry = getattr(invocation.turn_context, "telemetry", None)
        if telemetry is not None:
            try:
                telemetry.record_tool_execution(  # type: ignore[attr-defined]
                    tool_name=invocation.tool_name,
                    duration=duration,
                    success=success,
                    error=error,
                )
            except Exception:  # pragma: no cover - telemetry should not break tools
                pass
    return result


__all__ = [
    "ToolHandler",
    "ToolInvocation",
    "ToolKind",
    "ToolOutput",
    "execute_handler",
]
