import asyncio
from pathlib import Path
from types import SimpleNamespace

from agent import Tool
from policies import ApprovalPolicy, ExecutionContext, SandboxPolicy
from tools.handler import ToolInvocation
from tools.handlers.shell import ShellHandler
from tools.payload import ToolPayload
from tools_run_terminal_cmd import run_terminal_cmd_tool_def


def _make_tool(fn):
    definition = run_terminal_cmd_tool_def()
    return Tool(
        name=definition["name"],
        description=definition["description"],
        input_schema=definition["input_schema"],
        fn=fn,
        capabilities={"exec_shell"},
    )


def _make_invocation(handler, exec_context, arguments, *, approver=None):
    turn_context = SimpleNamespace(exec_context=exec_context)
    if approver is not None:
        turn_context.request_approval = approver
    session = SimpleNamespace()
    return ToolInvocation(
        session=session,
        turn_context=turn_context,
        tracker=None,
        sub_id="test",
        call_id="call-1",
        tool_name="run_terminal_cmd",
        payload=ToolPayload.function(arguments),
    )


def test_shell_handler_executes_when_allowed():
    captured = {}

    def impl(arguments, tracker=None):
        captured.update(arguments)
        return "ok"

    handler = ShellHandler(_make_tool(impl))
    exec_context = ExecutionContext(
        cwd=Path.cwd(),
        sandbox_policy=SandboxPolicy.NONE,
        approval_policy=ApprovalPolicy.NEVER,
    )
    invocation = _make_invocation(handler, exec_context, {"command": "echo hi", "is_background": False})

    result = asyncio.run(handler.handle(invocation))

    assert result.success is True
    assert captured["command"] == "echo hi"


def test_shell_handler_blocks_command_by_policy():
    handler = ShellHandler(_make_tool(lambda payload, tracker=None: "should not run"))
    exec_context = ExecutionContext(
        cwd=Path.cwd(),
        sandbox_policy=SandboxPolicy.RESTRICTED,
        approval_policy=ApprovalPolicy.NEVER,
        blocked_commands=("echo",),
    )
    invocation = _make_invocation(handler, exec_context, {"command": "echo hi", "is_background": False})

    result = asyncio.run(handler.handle(invocation))

    assert result.success is False
    assert "blocked" in result.content


def test_shell_handler_denies_when_approval_rejected():
    handler = ShellHandler(_make_tool(lambda payload, tracker=None: "nope"))
    exec_context = ExecutionContext(
        cwd=Path.cwd(),
        sandbox_policy=SandboxPolicy.NONE,
        approval_policy=ApprovalPolicy.ALWAYS,
    )
    invocation = _make_invocation(
        handler,
        exec_context,
        {"command": "echo hi", "is_background": False},
        approver=lambda **_: False,
    )

    result = asyncio.run(handler.handle(invocation))

    assert result.success is False
    assert "denied" in result.content


def test_shell_handler_executes_when_approval_granted():
    handler = ShellHandler(_make_tool(lambda payload, tracker=None: "done"))
    exec_context = ExecutionContext(
        cwd=Path.cwd(),
        sandbox_policy=SandboxPolicy.NONE,
        approval_policy=ApprovalPolicy.ALWAYS,
    )
    invocation = _make_invocation(
        handler,
        exec_context,
        {"command": "echo hi", "is_background": False},
        approver=lambda **_: True,
    )

    result = asyncio.run(handler.handle(invocation))

    assert result.success is True
    assert result.content == "done"


def test_shell_handler_enforces_timeout_limit():
    observed = {}

    def impl(arguments, tracker=None):
        observed.update(arguments)
        return "ok"

    handler = ShellHandler(_make_tool(impl))
    exec_context = ExecutionContext(
        cwd=Path.cwd(),
        sandbox_policy=SandboxPolicy.NONE,
        approval_policy=ApprovalPolicy.NEVER,
        timeout_seconds=1.5,
    )
    invocation = _make_invocation(
        handler,
        exec_context,
        {"command": "sleep 5", "is_background": False, "timeout": 10},
    )

    result = asyncio.run(handler.handle(invocation))

    assert result.success is True
    assert observed["timeout"] == 1.5
