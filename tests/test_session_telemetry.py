from session.telemetry import SessionTelemetry, ToolExecutionEvent


def test_session_telemetry_records_events():
    telemetry = SessionTelemetry()
    telemetry.record_tool_execution(
        tool_name="echo",
        call_id="call-1",
        turn=2,
        duration=0.5,
        success=True,
        input_size=10,
        output_size=20,
    )

    assert telemetry.tool_executions
    event = telemetry.tool_executions[0]
    assert isinstance(event, ToolExecutionEvent)
    assert event.tool_name == "echo"
    stats = telemetry.tool_stats("echo")
    assert stats["calls"] == 1
    otel = telemetry.export_otel()
    assert "tool.echo" in otel
    assert "call-1" in otel


def test_session_telemetry_tracks_errors():
    telemetry = SessionTelemetry()
    telemetry.record_tool_execution(
        tool_name="grep",
        call_id="call-2",
        turn=1,
        duration=1.0,
        success=False,
        error="boom",
        input_size=5,
        output_size=0,
    )

    stats = telemetry.tool_stats("grep")
    assert stats["errors"] == 1
    assert stats["success_rate"] == 0.0
