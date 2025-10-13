"""Tool handler registry for dispatch and telemetry."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

from .handler import ToolHandler, ToolInvocation, ToolOutput, execute_handler
from .spec import ToolSpec


@dataclass
class ConfiguredToolSpec:
    """A tool specification coupled with runtime metadata."""

    spec: ToolSpec
    supports_parallel: bool = False


class ToolRegistry:
    """Central registry mapping tool names to handlers."""

    def __init__(self, handlers: Dict[str, ToolHandler]):
        self._handlers = dict(handlers)

    def get_handler(self, name: str) -> Optional[ToolHandler]:
        return self._handlers.get(name)

    def register_handler(self, name: str, handler: ToolHandler) -> None:
        self._handlers[name] = handler

    async def dispatch(self, invocation: ToolInvocation) -> ToolOutput:
        handler = self.get_handler(invocation.tool_name)
        if handler is None:
            return ToolOutput(
                content=f"tool '{invocation.tool_name}' not found",
                success=False,
            )

        if not handler.matches_kind(invocation.payload):
            return ToolOutput(
                content=f"tool '{invocation.tool_name}' received incompatible payload",
                success=False,
            )

        return await execute_handler(handler, invocation)


class ToolRegistryBuilder:
    """Builder object for constructing tool registries."""

    def __init__(self) -> None:
        self.handlers: Dict[str, ToolHandler] = {}
        self.specs: List[ConfiguredToolSpec] = []

    def register_handler(self, name: str, handler: ToolHandler) -> None:
        if name in self.handlers:
            print(
                f"Warning: overwriting handler for tool '{name}'",
                file=sys.stderr,
            )
        self.handlers[name] = handler

    def add_spec(self, spec: ToolSpec, *, supports_parallel: bool = False) -> None:
        self.specs.append(ConfiguredToolSpec(spec, supports_parallel))

    def build(self) -> tuple[list[ConfiguredToolSpec], ToolRegistry]:
        return (list(self.specs), ToolRegistry(self.handlers))


__all__ = [
    "ConfiguredToolSpec",
    "ToolRegistry",
    "ToolRegistryBuilder",
]
