"""Reusable harness for exercising tool handlers in tests."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from unittest.mock import Mock

from tools.handler import ToolHandler, ToolInvocation, ToolOutput, ToolKind
from tools.payload import ToolPayload
from session.turn_diff_tracker import TurnDiffTracker


class _AsyncDummyTelemetry:
    """Minimal telemetry stub that records tool execution events."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record_tool_execution(self, **kwargs: Any) -> None:  # pragma: no cover - simple collector
        self.records.append(kwargs)


@dataclass
class MockToolContext:
    """Mock context object providing telemetry + tracker for handlers."""

    session: Mock
    turn_context: Mock
    tracker: TurnDiffTracker
    sub_id: str = "test-sub"

    @classmethod
    def create(cls, *, turn_id: int = 1, cwd: Optional[Path] = None) -> "MockToolContext":
        session = Mock()
        telemetry = _AsyncDummyTelemetry()
        turn_context = Mock()
        turn_context.cwd = (cwd or Path.cwd()).resolve()
        turn_context.telemetry = telemetry
        turn_context.turn_index = turn_id

        tracker = TurnDiffTracker(turn_id=turn_id)

        return cls(
            session=session,
            turn_context=turn_context,
            tracker=tracker,
        )


class ToolTestHarness:
    """Helper for invoking `ToolHandler` implementations under test."""

    def __init__(self, handler: ToolHandler, *, context: Optional[MockToolContext] = None):
        self.handler = handler
        self.context = context or MockToolContext.create()

    async def invoke(
        self,
        tool_name: str,
        payload: Dict[str, Any],
        *,
        call_id: str = "test-call",
    ) -> ToolOutput:
        invocation = ToolInvocation(
            session=self.context.session,
            turn_context=self.context.turn_context,
            tracker=self.context.tracker,
            sub_id=self.context.sub_id,
            call_id=call_id,
            tool_name=tool_name,
            payload=ToolPayload.function(payload),
        )
        return await self.handler.handle(invocation)

    def assert_success(self, output: ToolOutput) -> None:
        assert output.success, f"Expected success but got failure: {output.content}"

    def assert_error(self, output: ToolOutput, expected_msg: Optional[str] = None) -> None:
        assert not output.success, "Expected failure but tool succeeded"
        if expected_msg:
            assert expected_msg in output.content, f"Missing expected message '{expected_msg}'"

    def telemetry_records(self) -> list[dict[str, Any]]:
        return list(self.context.turn_context.telemetry.records)

    def tracker(self) -> TurnDiffTracker:
        return self.context.tracker


__all__ = ["ToolTestHarness", "MockToolContext"]
