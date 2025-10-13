"""Shell handler enforcing execution policies before delegating to the tool."""
from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any, TYPE_CHECKING

from policies import ApprovalPolicy, ExecutionContext, SandboxPolicy
from tools.handler import ToolHandler, ToolInvocation, ToolKind, ToolOutput
from tools.payload import FunctionToolPayload, ToolPayload
from tools.schemas import validate_tool_input

from .function import FunctionToolHandler

if TYPE_CHECKING:  # pragma: no cover
    from agent import Tool


class ShellHandler(ToolHandler):
    """Adapter for ``run_terminal_cmd`` that honors execution policies."""

    def __init__(self, tool: "Tool") -> None:
        self._tool = tool
        self._accepts_tracker = FunctionToolHandler._detect_tracker_support(tool.fn)

    @property
    def kind(self) -> ToolKind:
        return ToolKind.FUNCTION

    def matches_kind(self, payload: ToolPayload) -> bool:
        return isinstance(payload, FunctionToolPayload)

    async def handle(self, invocation: ToolInvocation) -> ToolOutput:
        payload = invocation.payload
        if not isinstance(payload, FunctionToolPayload):
            return ToolOutput(content="shell handler received non-function payload", success=False)

        try:
            arguments = validate_tool_input(self._tool.name, payload.arguments)
        except ValueError as exc:
            return ToolOutput(content=str(exc), success=False, metadata={"error_type": "validation"})

        command = str(arguments.get("command", "")).strip()
        exec_context = self._resolve_exec_context(invocation)
        allowed, reason = exec_context.can_execute_command(command)
        if not allowed:
            return ToolOutput(content=f"Command blocked by policy: {reason}", success=False)

        if exec_context.requires_approval(self._tool.name, is_write=False):
            approved = await self._request_approval(invocation, command)
            if not approved:
                return ToolOutput(content="Command execution denied by policy", success=False)

        timeout_limit = exec_context.timeout_seconds
        if timeout_limit is not None:
            timeout_val = arguments.get("timeout")
            try:
                timeout_float = float(timeout_val) if timeout_val is not None else None
            except (TypeError, ValueError):
                timeout_float = None
            if timeout_float is None or timeout_float > timeout_limit:
                arguments["timeout"] = timeout_limit

        try:
            result = await self._invoke_tool(arguments, invocation)
        except Exception as exc:  # pragma: no cover - defensive envelope
            return ToolOutput(content=str(exc), success=False, metadata={"exception": repr(exc)})

        if isinstance(result, ToolOutput):
            return result
        if isinstance(result, str):
            return ToolOutput(content=result, success=True)
        return ToolOutput(content=str(result), success=True)

    async def _invoke_tool(self, arguments: dict[str, Any], invocation: ToolInvocation) -> Any:
        def _call() -> Any:
            if invocation.tracker is not None and self._accepts_tracker:
                return self._tool.fn(arguments, invocation.tracker)
            return self._tool.fn(arguments)

        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, _call)
        except RuntimeError:
            return _call()

    def _resolve_exec_context(self, invocation: ToolInvocation) -> ExecutionContext:
        context = getattr(invocation.turn_context, "exec_context", None)
        if isinstance(context, ExecutionContext):
            return context

        cwd_attr = getattr(invocation.turn_context, "cwd", None) or getattr(invocation.session, "cwd", None)
        cwd = Path(cwd_attr) if cwd_attr else Path.cwd()
        return ExecutionContext(
            cwd=cwd,
            sandbox_policy=SandboxPolicy.NONE,
            approval_policy=ApprovalPolicy.NEVER,
        )

    async def _request_approval(self, invocation: ToolInvocation, command: str) -> bool:
        approver = getattr(invocation.turn_context, "request_approval", None)
        if approver is None:
            approver = getattr(invocation.session, "request_approval", None)
        if approver is None:
            return False
        try:
            result = approver(tool_name=self._tool.name, command=command)
            if inspect.isawaitable(result):
                result = await result
            return bool(result)
        except Exception:
            return False


__all__ = ["ShellHandler"]
