"""Payload types for tool invocations."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Mapping


class ToolPayloadKind(Enum):
    """Kinds of payloads supported by the tool system."""

    FUNCTION = "function"
    UNIFIED_EXEC = "unified_exec"
    MCP = "mcp"
    CUSTOM = "custom"


@dataclass(frozen=True)
class ToolPayload:
    """Base payload object passed to tool handlers."""

    kind: ToolPayloadKind

    @classmethod
    def function(cls, arguments: Mapping[str, Any]) -> "FunctionToolPayload":
        return FunctionToolPayload(arguments=dict(arguments))

    @classmethod
    def unified_exec(cls, command: str, arguments: Mapping[str, Any]) -> "UnifiedExecToolPayload":
        return UnifiedExecToolPayload(command=command, arguments=dict(arguments))

    @classmethod
    def mcp(cls, server: str, tool: str, arguments: Mapping[str, Any]) -> "MCPToolPayload":
        return MCPToolPayload(server=server, tool=tool, arguments=dict(arguments))

    @classmethod
    def custom(cls, name: str, payload: Mapping[str, Any]) -> "CustomToolPayload":
        return CustomToolPayload(name=name, payload=dict(payload))


@dataclass(frozen=True)
class FunctionToolPayload(ToolPayload):
    """Payload for function tools with JSON arguments."""

    arguments: Dict[str, Any]

    def __init__(self, arguments: Dict[str, Any]):
        object.__setattr__(self, "kind", ToolPayloadKind.FUNCTION)
        object.__setattr__(self, "arguments", arguments)


@dataclass(frozen=True)
class UnifiedExecToolPayload(ToolPayload):
    """Payload invoking unified command execution."""

    command: str
    arguments: Dict[str, Any]

    def __init__(self, command: str, arguments: Dict[str, Any]):
        object.__setattr__(self, "kind", ToolPayloadKind.UNIFIED_EXEC)
        object.__setattr__(self, "command", command)
        object.__setattr__(self, "arguments", arguments)


@dataclass(frozen=True)
class MCPToolPayload(ToolPayload):
    """Payload delegating to an MCP server tool."""

    server: str
    tool: str
    arguments: Dict[str, Any]

    def __init__(self, server: str, tool: str, arguments: Dict[str, Any]):
        object.__setattr__(self, "kind", ToolPayloadKind.MCP)
        object.__setattr__(self, "server", server)
        object.__setattr__(self, "tool", tool)
        object.__setattr__(self, "arguments", arguments)


@dataclass(frozen=True)
class CustomToolPayload(ToolPayload):
    """Payload for custom tool integrations."""

    name: str
    payload: Dict[str, Any]

    def __init__(self, name: str, payload: Dict[str, Any]):
        object.__setattr__(self, "kind", ToolPayloadKind.CUSTOM)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "payload", payload)


__all__ = [
    "CustomToolPayload",
    "FunctionToolPayload",
    "MCPToolPayload",
    "ToolPayload",
    "ToolPayloadKind",
    "UnifiedExecToolPayload",
]
