"""Compatibility helpers bridging legacy ``Tool`` objects to the new system."""
from __future__ import annotations

from typing import Iterable, Sequence, Tuple, TYPE_CHECKING

from .handlers.function import FunctionToolHandler
from .registry import ConfiguredToolSpec, ToolRegistry, ToolRegistryBuilder
from .spec import ToolSpec


_PARALLEL_SAFE_CAPS = {"read_fs"}
_PARALLEL_UNSAFE_CAPS = {"write_fs", "exec_shell", "network"}


def _supports_parallel(tool: "Tool") -> bool:
    if not tool.capabilities:
        return True
    if tool.capabilities & _PARALLEL_UNSAFE_CAPS:
        return False
    if tool.capabilities & _PARALLEL_SAFE_CAPS:
        return True
    return False

if TYPE_CHECKING:  # pragma: no cover
    from agent import Tool


def build_registry_from_tools(tools: Sequence["Tool"]) -> Tuple[list[ConfiguredToolSpec], ToolRegistry]:
    """Create a ``ToolRegistry`` and specs list from legacy ``Tool`` instances."""
    builder = ToolRegistryBuilder()
    for tool in tools:
        handler = FunctionToolHandler(tool)
        builder.register_handler(tool.name, handler)
        builder.add_spec(
            ToolSpec(
                name=tool.name,
                description=tool.description,
                input_schema=tool.input_schema,
            ),
            supports_parallel=_supports_parallel(tool),
        )
    return builder.build()


def tool_specs_from_tools(tools: Iterable["Tool"]) -> list[ToolSpec]:
    """Convert legacy tools to ``ToolSpec`` objects."""
    return [
        ToolSpec(name=tool.name, description=tool.description, input_schema=tool.input_schema)
        for tool in tools
    ]


__all__ = ["build_registry_from_tools", "tool_specs_from_tools"]
