"""Tool routing utilities for translating model outputs into handler calls."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .handler import ToolInvocation
from .payload import ToolPayload
from .registry import ConfiguredToolSpec, ToolRegistry


@dataclass
class ToolCall:
    """Represents a parsed tool call emitted by the model."""

    tool_name: str
    call_id: str
    payload: ToolPayload


class ToolRouter:
    """Routes tool calls through a registry and returns tool_result blocks."""

    def __init__(self, registry: ToolRegistry, specs: list[ConfiguredToolSpec]):
        self._registry = registry
        self._specs = list(specs)

    def tool_supports_parallel(self, tool_name: str) -> bool:
        for spec in self._specs:
            if spec.spec.name == tool_name:
                return spec.supports_parallel
        return False

    @staticmethod
    def build_tool_call(item: Dict[str, Any]) -> Optional[ToolCall]:
        item_type = item.get("type")
        if item_type != "tool_use":
            return None

        name = item.get("name", "")
        call_id = item.get("id", "")
        arguments = item.get("input", {})
        if not isinstance(arguments, dict):
            arguments = {}

        if "/" in name:
            server, tool = name.split("/", 1)
            payload = ToolPayload.mcp(server, tool, arguments)
        else:
            payload = ToolPayload.function(arguments)

        return ToolCall(tool_name=name, call_id=call_id, payload=payload)

    async def dispatch_tool_call(
        self,
        *,
        session: Any,
        turn_context: Any,
        tracker: Any,
        sub_id: str,
        call: ToolCall,
    ) -> Dict[str, Any]:
        invocation = ToolInvocation(
            session=session,
            turn_context=turn_context,
            tracker=tracker,
            sub_id=sub_id,
            call_id=call.call_id,
            tool_name=call.tool_name,
            payload=call.payload,
        )

        output = await self._registry.dispatch(invocation)
        return {
            "type": "tool_result",
            "tool_use_id": call.call_id,
            "content": output.content,
            "is_error": not output.success,
        }


__all__ = ["ToolCall", "ToolRouter"]
