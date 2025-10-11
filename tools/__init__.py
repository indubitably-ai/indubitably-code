"""Tool system abstractions for the indubitably agent."""

from .handler import ToolHandler, ToolInvocation, ToolKind, ToolOutput
from .handlers import FunctionToolHandler
from .legacy import build_registry_from_tools, tool_specs_from_tools
from .payload import (
    FunctionToolPayload,
    MCPToolPayload,
    ToolPayload,
)
from .registry import ToolRegistry, ToolRegistryBuilder, ConfiguredToolSpec
from .router import ToolCall, ToolRouter
from .parallel import ToolCallRuntime
from .runtime import ToolRuntime, ToolRuntimeResult
from .schemas import (
    ApplyPatchInput,
    CreateFileInput,
    DeleteFileInput,
    EditFileInput,
    GrepInput,
    LineEditInput,
    ReadFileInput,
    RenameFileInput,
    RunTerminalCmdInput,
    TemplateBlockInput,
    TodoItemInput,
    TodoWriteInput,
    ToolSchema,
    validate_tool_input,
)
from .spec import ToolSpec

__all__ = [
    "ConfiguredToolSpec",
    "FunctionToolPayload",
    "MCPToolPayload",
    "ToolCall",
    "FunctionToolHandler",
    "build_registry_from_tools",
    "tool_specs_from_tools",
    "ToolHandler",
    "ToolInvocation",
    "ToolKind",
    "ToolOutput",
    "ToolPayload",
    "ToolRegistry",
    "ToolRegistryBuilder",
    "ToolRouter",
    "ToolSpec",
    "ToolCallRuntime",
    "ToolRuntime",
    "ToolRuntimeResult",
    "ToolSchema",
    "ReadFileInput",
    "RunTerminalCmdInput",
    "GrepInput",
    "EditFileInput",
    "CreateFileInput",
    "DeleteFileInput",
    "LineEditInput",
    "RenameFileInput",
    "ApplyPatchInput",
    "TemplateBlockInput",
    "TodoItemInput",
    "TodoWriteInput",
    "validate_tool_input",
]
