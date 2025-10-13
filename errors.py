"""Structured tool error types."""
from __future__ import annotations

from enum import Enum


class ErrorType(Enum):
    """Classification of tool errors."""

    FATAL = "fatal"
    RECOVERABLE = "recoverable"
    VALIDATION = "validation"


class ToolError(Exception):
    """Base class for tool execution errors."""

    def __init__(self, message: str, error_type: ErrorType = ErrorType.RECOVERABLE) -> None:
        super().__init__(message)
        self.message = message
        self.error_type = error_type

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.message


class FatalToolError(ToolError):
    """Error indicating the agent should abort execution."""

    def __init__(self, message: str) -> None:
        super().__init__(message, ErrorType.FATAL)


class ValidationToolError(ToolError):
    """Error indicating invalid tool input supplied by the model."""

    def __init__(self, message: str) -> None:
        super().__init__(message, ErrorType.VALIDATION)


class SandboxToolError(ToolError):
    """Error raised when sandbox or policy constraints are violated."""

    def __init__(self, message: str) -> None:
        super().__init__(message, ErrorType.FATAL)


__all__ = [
    "ErrorType",
    "FatalToolError",
    "SandboxToolError",
    "ToolError",
    "ValidationToolError",
    "ValidationError",
]

# Backwards-compatible alias matching migration plan naming.
ValidationError = ValidationToolError
