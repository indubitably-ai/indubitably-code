from io import StringIO

from session import OtelExporter, SessionTelemetry


def test_otel_exporter_writes_to_sink():
    telemetry = SessionTelemetry()
    telemetry.record_tool_execution(
        tool_name="shell",
        call_id="call-1",
        turn=1,
        duration=0.12,
        success=True,
        input_size=42,
        output_size=256,
    )

    buffer = StringIO()
    exporter = OtelExporter(service_name="test-agent", sink=buffer)
    telemetry.flush_to_otel(exporter)

    payload = buffer.getvalue().strip()
    assert payload
    assert '"service.name": "test-agent"' in payload
    assert '"tool.name": "shell"' in payload


def test_otel_exporter_buffers_without_sink():
    exporter = OtelExporter(service_name="buffered")
    exporter.export([{"name": "tool.shell", "attributes": {}}])
    payloads = exporter.buffered_payloads()
    assert len(payloads) == 1
    assert '"service.name": "buffered"' in payloads[0]
