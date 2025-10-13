"""Tool execution runtime coordinating registry/telemetry integration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from .handler import ToolInvocation
from .payload import ToolPayload
from .registry import ToolRegistry


@dataclass
class ToolRuntimeResult:
    """Result bundle returned by ToolRuntime.dispatch."""

    output: Dict[str, Any]
    success: bool


class ToolRuntime:
    """Entry point for executing tool calls via a registry."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def dispatch(
        self,
        *,
        session: Any,
        turn_context: Any,
        tracker: Any,
        sub_id: str,
        tool_name: str,
        call_id: str,
        payload: ToolPayload,
    ) -> ToolRuntimeResult:
        invocation = ToolInvocation(
            session=session,
            turn_context=turn_context,
            tracker=tracker,
            sub_id=sub_id,
            call_id=call_id,
            tool_name=tool_name,
            payload=payload,
        )
        output = await self._registry.dispatch(invocation)
        metadata = dict(output.metadata or {})
        return ToolRuntimeResult(
            output={
                "type": "tool_result",
                "tool_use_id": call_id,
                "content": output.content,
                "is_error": not output.success,
                "metadata": metadata,
                "error_type": metadata.get("error_type"),
            },
            success=output.success,
        )
