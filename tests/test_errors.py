from errors import ErrorType, FatalToolError, SandboxToolError, ToolError, ValidationError


def test_error_type_values():
    assert ErrorType.FATAL.value == "fatal"
    assert ErrorType.RECOVERABLE.value == "recoverable"
    assert ErrorType.VALIDATION.value == "validation"


def test_tool_error_classes():
    err = ToolError("oops")
    assert err.message == "oops"
    assert err.error_type == ErrorType.RECOVERABLE

    fatal = FatalToolError("boom")
    assert fatal.error_type == ErrorType.FATAL

    sandbox = SandboxToolError("policy")
    assert sandbox.error_type == ErrorType.FATAL

    validation = ValidationError("bad")
    assert validation.error_type == ErrorType.VALIDATION
