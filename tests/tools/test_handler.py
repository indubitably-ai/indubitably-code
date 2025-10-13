import asyncio

from errors import ErrorType, FatalToolError, ToolError
from tools.handler import ToolInvocation, ToolKind, ToolOutput, execute_handler
from tools.payload import ToolPayload


class DummyTelemetry:
    def __init__(self) -> None:
        self.records = []

    def record_tool_execution(self, **kwargs):  # pragma: no cover - simple collector
        self.records.append(kwargs)


class DummyHandler:
    @property
    def kind(self) -> ToolKind:
        return ToolKind.FUNCTION

    def matches_kind(self, payload):
        return True

    async def handle(self, invocation):
        return ToolOutput(content="ok", success=True)


def test_execute_handler_records_telemetry():
    handler = DummyHandler()
    payload = ToolPayload.function({"value": 1})
    telemetry = DummyTelemetry()
    turn_context = type("Ctx", (), {"telemetry": telemetry, "turn_index": 3})()
    invocation = ToolInvocation(
        session=None,
        turn_context=turn_context,
        tracker=None,
        sub_id="sub",
        call_id="call-123",
        tool_name="echo",
        payload=payload,
    )

    result = asyncio.run(execute_handler(handler, invocation))

    assert result.success is True
    assert telemetry.records
    record = telemetry.records[0]
    assert record["tool_name"] == "echo"
    assert record["call_id"] == "call-123"
    assert record["turn"] == 3
    assert record["input_size"] > 0
    assert record["output_size"] > 0


class ErrorHandler(DummyHandler):
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def handle(self, invocation):  # type: ignore[override]
        raise self._exc


def test_execute_handler_handles_tool_error():
    telemetry = DummyTelemetry()
    turn_context = type("Ctx", (), {"telemetry": telemetry, "turn_index": 1})()
    invocation = ToolInvocation(
        session=None,
        turn_context=turn_context,
        tracker=None,
        sub_id="sub",
        call_id="call-err",
        tool_name="writer",
        payload=ToolPayload.function({}),
    )

    handler = ErrorHandler(ToolError("validation failed"))
    result = asyncio.run(execute_handler(handler, invocation))

    assert result.success is False
    assert "validation failed" in result.content
    assert result.metadata["error_type"] == ErrorType.RECOVERABLE.value
    assert telemetry.records and telemetry.records[0]["success"] is False


def test_execute_handler_raises_fatal_tool_error():
    telemetry = DummyTelemetry()
    turn_context = type("Ctx", (), {"telemetry": telemetry, "turn_index": 2})()
    invocation = ToolInvocation(
        session=None,
        turn_context=turn_context,
        tracker=None,
        sub_id="sub",
        call_id="call-fatal",
        tool_name="danger",
        payload=ToolPayload.function({}),
    )

    handler = ErrorHandler(FatalToolError("boom"))

    result = asyncio.run(execute_handler(handler, invocation))

    assert result.success is False
    assert result.metadata["error_type"] == ErrorType.FATAL.value
    assert telemetry.records and telemetry.records[0]["success"] is False
