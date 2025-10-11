"""Function-based tool handler wrapping legacy synchronous tools."""
from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable, Dict, TYPE_CHECKING

from ..handler import ToolHandler, ToolInvocation, ToolKind, ToolOutput
from ..schemas import validate_tool_input
from ..payload import FunctionToolPayload, ToolPayload

if TYPE_CHECKING:  # pragma: no cover
    from agent import Tool


class FunctionToolHandler(ToolHandler):
    """Adapter that allows legacy ``Tool`` objects to participate in the new system."""

    def __init__(self, tool: "Tool") -> None:
        self._tool = tool
        self._accepts_tracker = self._detect_tracker_support(tool.fn)

    @property
    def kind(self) -> ToolKind:
        return ToolKind.FUNCTION

    def matches_kind(self, payload: ToolPayload) -> bool:
        return isinstance(payload, FunctionToolPayload)

    async def handle(self, invocation: ToolInvocation) -> ToolOutput:
        if not isinstance(invocation.payload, FunctionToolPayload):
            return ToolOutput(
                content="function handler received non-function payload",
                success=False,
            )

        try:
            arguments = validate_tool_input(self._tool.name, invocation.payload.arguments)
        except ValueError as exc:
            return ToolOutput(content=str(exc), success=False)

        def _call() -> Any:
            if invocation.tracker is not None and self._accepts_tracker:
                return self._tool.fn(arguments, invocation.tracker)
            return self._tool.fn(arguments)

        try:
            try:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, _call)
            except RuntimeError:
                # No running loop (e.g., synchronous context)
                result = _call()
        except Exception as exc:  # pragma: no cover - surfaced in ToolOutput
            return ToolOutput(content=str(exc), success=False, metadata={"exception": repr(exc)})

        if isinstance(result, ToolOutput):
            return result
        if isinstance(result, str):
            content = result
        else:
            content = str(result)
        return ToolOutput(content=content, success=True)

    @property
    def tool(self) -> "Tool":  # pragma: no cover - convenience for callers
        return self._tool

    @staticmethod
    def _detect_tracker_support(fn: Callable[..., Any]) -> bool:
        try:
            signature = inspect.signature(fn)
        except (TypeError, ValueError):  # pragma: no cover - builtins, etc.
            return False

        params = list(signature.parameters.values())
        if not params:
            return False

        for param in params:
            if param.name == "tracker":
                return True
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                return True

        if len(params) >= 2:
            return True
        return False
