"""Core tool handler protocol and supporting data structures."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Protocol

from errors import ErrorType, ToolError
from .payload import ToolPayload
from .tool_summary import summarize_tool_call, truncate_text


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
    error_summary: str | None = None
    request_summary = summarize_tool_call(invocation.tool_name, invocation.payload)
    response_text: str = ""
    try:
        result = await handler.handle(invocation)
        success = result.success
        error: str | None = None
        response_text = result.content or ""
    except ToolError as exc:
        success = False
        error = exc.message
        error_summary = exc.message.split("\n", 1)[0]
        result = ToolOutput(
            content=exc.message,
            success=False,
            metadata={"error_type": exc.error_type.value},
        )
        response_text = result.content or ""
    except Exception as exc:  # pragma: no cover - defensive envelope
        success = False
        error = str(exc)
        error_summary = str(exc).split("\n", 1)[0]
        result = ToolOutput(
            content=f"tool execution failed: {exc}",
            success=False,
            metadata={"error_type": ErrorType.FATAL.value},
        )
        response_text = result.content or ""
    finally:
        duration = time.time() - start
        telemetry = getattr(invocation.turn_context, "telemetry", None)
        if telemetry is not None:
            try:
                response_preview = truncate_text(response_text, limit=160) if response_text else None
                outcome = response_preview or ("ok" if success else "error")
                message = f"{request_summary} -> {outcome} [{int(duration * 1000)}ms]"
                telemetry.record_tool_execution(  # type: ignore[attr-defined]
                    tool_name=invocation.tool_name,
                    call_id=invocation.call_id,
                    turn=getattr(invocation.turn_context, "turn_index", 0),
                    duration=duration,
                    success=success,
                    error=error,
                    input_size=_estimate_payload_size(invocation.payload),
                    output_size=len((result.content or "").encode("utf-8")),
                    truncated=bool(result.metadata and result.metadata.get("truncated")),
                    error_type=(result.metadata or {}).get("error_type"),
                    message=message,
                    error_summary=error_summary,
                    request_summary=request_summary,
                    response_preview=response_preview,
                )
            except Exception:  # pragma: no cover - telemetry should not break tools
                pass

    if not result.success:
        metadata = result.metadata or {}
        if "error_type" not in metadata:
            metadata["error_type"] = ErrorType.RECOVERABLE.value
            result.metadata = metadata

    return result


def _estimate_payload_size(payload: ToolPayload) -> int:
    data: Any
    if hasattr(payload, "arguments"):
        data = getattr(payload, "arguments")
    elif hasattr(payload, "payload"):
        data = getattr(payload, "payload")
    else:
        data = str(payload)
    try:
        serialized = json.dumps(data, ensure_ascii=False)
        return len(serialized.encode("utf-8"))
    except Exception:  # pragma: no cover - defensive
        return 0


__all__ = [
    "ToolHandler",
    "ToolInvocation",
    "ToolKind",
    "ToolOutput",
    "execute_handler",
]
