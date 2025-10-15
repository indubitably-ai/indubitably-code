from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from agent import Tool
from agent_runner import AgentRunOptions, AgentRunner
from tests.mocking import MockAnthropic
from tests.integration.helpers import queue_tool_turn
from tools_read import read_file_tool_def, read_file_impl
from session import SessionSettings


def _build_read_tool() -> Tool:
    definition = read_file_tool_def()
    return Tool(
        name=definition["name"],
        description=definition["description"],
        input_schema=definition["input_schema"],
        fn=read_file_impl,
        capabilities={"read_fs"},
    )


def test_otel_export_writes_jsonl_end_to_end(integration_workspace) -> None:
    """Agent run with telemetry export enabled should write OTEL JSONL."""

    # Prepare a small file to read
    integration_workspace.write("sample.txt", "hello otel\n")

    # Mock model to request a read_file tool and finish
    client = MockAnthropic()
    queue_tool_turn(
        client,
        tool_name="read_file",
        payloads=[{"path": "sample.txt"}],
        final_text="done",
    )

    # Enable OTEL export to a temp path
    base = SessionSettings()
    export_dir = Path("run_artifacts/otel")
    export_dir.mkdir(parents=True, exist_ok=True)
    export_path = export_dir / "events.jsonl"
    telemetry = replace(
        base.telemetry,
        enable_export=True,
        export_path=export_path,
        service_name="indubitably-agent-local",
    )
    settings = replace(base, telemetry=telemetry)

    runner = AgentRunner(
        tools=[_build_read_tool()],
        options=AgentRunOptions(max_turns=2, verbose=False),
        client=client,
        session_settings=settings,
    )

    runner.run("Read sample.txt")

    # Verify that the JSONL file exists and contains an OTEL-formatted event
    assert export_path.exists(), f"expected export file at {export_path}"
    content = export_path.read_text(encoding="utf-8").strip()
    assert content, "expected non-empty OTEL export file"

    # The exporter now writes one event per line: {"resource": {...}, "event": {...}}
    first_line = content.splitlines()[0]
    payload = json.loads(first_line)
    assert payload["resource"]["service.name"] == "indubitably-agent-local"
    event = payload.get("event") or {}
    attrs = event.get("attributes") or {}
    assert attrs.get("tool.name") == "read_file"
    assert attrs.get("tool.success") is True
    assert "tool.message" in attrs


