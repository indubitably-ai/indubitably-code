from __future__ import annotations

import json
import os
import time
import urllib.request
import urllib.parse
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from agent import Tool
from agent_runner import AgentRunOptions, AgentRunner
from tests.mocking import MockAnthropic
from tests.integration.helpers import queue_tool_turn
from tools_read import read_file_tool_def, read_file_impl
from session import SessionSettings
from policies import ApprovalPolicy


def _build_read_tool() -> Tool:
    definition = read_file_tool_def()
    return Tool(
        name=definition["name"],
        description=definition["description"],
        input_schema=definition["input_schema"],
        fn=read_file_impl,
        capabilities={"read_fs"},
    )


@pytest.mark.skipif(os.getenv("LOKI_SMOKE") != "1", reason="LOKI_SMOKE not enabled")
def test_otel_event_reaches_loki(integration_workspace) -> None:
    """Smoke test: write an event and query Loki for it."""

    # Unique marker to find in Loki
    marker = f"marker-{uuid4()}"
    integration_workspace.write("sample.txt", marker + "\n")

    client = MockAnthropic()
    queue_tool_turn(
        client,
        tool_name="read_file",
        payloads=[{"path": "sample.txt"}],
        final_text="done",
    )

    # Export to repo-root path tailed by the collector
    repo_root = Path(__file__).resolve().parents[2]
    export_dir = repo_root / "run_artifacts" / "otel"
    export_dir.mkdir(parents=True, exist_ok=True)
    export_path = export_dir / "events.jsonl"

    base = SessionSettings()
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

    # Small wait to allow the collector to ship the new line
    time.sleep(1.0)

    loki = os.getenv("LOKI_URL", "http://localhost:3100")
    # Instant query for the marker in log body
    params = {
        "query": f"{{}} |= \"{marker}\"",
        "limit": "100",
    }
    url = f"{loki}/loki/api/v1/query?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=8) as resp:
        body = resp.read().decode("utf-8")
    data = json.loads(body)
    assert data.get("status") == "success"
    streams = data.get("data", {}).get("result", [])
    assert any(marker in (entry[1] if isinstance(entry, list) else "") for s in streams for entry in s.get("values", [])), (
        "expected to find marker in Loki logs"
    )


@pytest.mark.skipif(os.getenv("LOKI_SMOKE") != "1", reason="LOKI_SMOKE not enabled")
def test_otel_policy_denied_event_in_loki(integration_workspace) -> None:
    """Smoke: policy_denied event should be shipped and visible in Loki body."""

    client = MockAnthropic()
    queue_tool_turn(
        client,
        tool_name="run_terminal_cmd",
        payloads=[{"command": "echo hi", "is_background": False}],
        final_text="denied",
    )

    repo_root = Path(__file__).resolve().parents[2]
    export_dir = repo_root / "run_artifacts" / "otel"
    export_dir.mkdir(parents=True, exist_ok=True)
    export_path = export_dir / "events.jsonl"

    base = SessionSettings()
    telemetry = replace(
        base.telemetry,
        enable_export=True,
        export_path=export_path,
        service_name="indubitably-agent-local",
    )
    # Force approval on every tool; no approver configured -> policy_denied
    execution = replace(base.execution, approval=ApprovalPolicy.ALWAYS)
    settings = replace(base, telemetry=telemetry, execution=execution)

    runner = AgentRunner(
        tools=[_build_read_tool()],  # tool registry includes run_terminal_cmd via legacy wiring
        options=AgentRunOptions(max_turns=1, verbose=False),
        client=client,
        session_settings=settings,
    )
    runner.run("Run echo hi (should require approval)")

    time.sleep(1.0)

    loki = os.getenv("LOKI_URL", "http://localhost:3100")
    # Search for the policy_denied marker in the log body JSON using instant query
    needle = '\\"tool.error_type\\": \\"policy_denied\\"'
    params = {
        "query": f"{{}} |= \"{needle}\"",
        "limit": "100",
    }
    url = f"{loki}/loki/api/v1/query?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=8) as resp:
        body = resp.read().decode("utf-8")
    data = json.loads(body)
    assert data.get("status") == "success"
    streams = data.get("data", {}).get("result", [])
    assert streams, "expected to find policy_denied event in Loki"


