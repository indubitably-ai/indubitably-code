from pathlib import Path

from policies import ApprovalPolicy, ExecutionContext, SandboxPolicy


def test_execution_context_blocks_in_strict_mode():
    ctx = ExecutionContext(
        cwd=Path.cwd(),
        sandbox_policy=SandboxPolicy.STRICT,
        approval_policy=ApprovalPolicy.NEVER,
    )
    allowed, reason = ctx.can_execute_command("ls")
    assert allowed is True

    allowed, reason = ctx.can_execute_command("python -V")
    assert allowed is False
    assert "not allowed" in reason


def test_execution_context_can_write_path():
    ctx = ExecutionContext(
        cwd=Path.cwd(),
        sandbox_policy=SandboxPolicy.RESTRICTED,
        approval_policy=ApprovalPolicy.ON_WRITE,
        allowed_paths=(Path.cwd(),),
    )
    allowed, reason = ctx.can_write_path(Path.cwd() / "file.txt")
    assert allowed is True

    allowed, reason = ctx.can_write_path(Path("/etc/hosts"))
    assert allowed is False
    assert "allowed paths" in reason or "system" in reason


def test_execution_context_requires_approval_on_write():
    ctx = ExecutionContext(
        cwd=Path.cwd(),
        sandbox_policy=SandboxPolicy.NONE,
        approval_policy=ApprovalPolicy.ON_WRITE,
    )
    assert ctx.requires_approval("tool", is_write=True) is True
    assert ctx.requires_approval("tool", is_write=False) is False
