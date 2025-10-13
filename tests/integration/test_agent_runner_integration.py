"""Integration tests for the headless agent runner."""
from __future__ import annotations

import json
import time
from typing import Dict, List, Tuple

from agent import Tool
from agent_runner import AgentRunOptions, AgentRunner
from tests.integration.helpers import queue_tool_turn
from tests.mocking import MockAnthropic, text_block, tool_use_block

from tools_create_file import create_file_tool_def, create_file_impl
from tools_read import read_file_tool_def, read_file_impl


def _build_create_file_tool() -> Tool:
    definition = create_file_tool_def()
    return Tool(
        name=definition["name"],
        description=definition["description"],
        input_schema=definition["input_schema"],
        fn=create_file_impl,
        capabilities={"write_fs"},
    )


def _build_read_file_tool() -> Tool:
    definition = read_file_tool_def()
    return Tool(
        name=definition["name"],
        description=definition["description"],
        input_schema=definition["input_schema"],
        fn=read_file_impl,
        capabilities={"read_fs"},
    )


def _build_flaky_tool() -> Tool:
    schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    def handler(payload: Dict[str, str]) -> str:
        raise RuntimeError("synthetic failure for cleanup test")

    return Tool(
        name="flaky_tool",
        description="Deliberately fails to exercise cleanup paths.",
        input_schema=schema,
        fn=handler,
        capabilities={"read_fs"},
    )
def test_agent_runner_creates_file_and_records_result(
    integration_workspace,
) -> None:
    """Ensure the runner executes write tools and records their output."""

    client = MockAnthropic()
    queue_tool_turn(
        client,
        tool_name="create_file",
        payloads=[{"path": "report.txt", "content": "integration ok"}],
        final_text="Created the file as requested.",
    )

    runner = AgentRunner(
        tools=[_build_create_file_tool()],
        options=AgentRunOptions(max_turns=2, verbose=False),
        client=client,
    )

    result = runner.run("Create report.txt with 'integration ok'.")

    created = integration_workspace.path("report.txt")
    assert created.exists()
    assert created.read_text(encoding="utf-8") == "integration ok"

    assert result.turns_used == 2
    assert result.tool_events, "expected tool event for create_file"
    assert any(event.tool_name == "create_file" for event in result.tool_events)


def test_agent_runner_dry_run_skips_execution_and_writes_audit(
    integration_workspace,
) -> None:
    """Dry-run mode should skip execution while emitting audit metadata."""

    audit_path = integration_workspace.path("audit.jsonl")
    changes_path = integration_workspace.path("changes.jsonl")

    client = MockAnthropic()
    queue_tool_turn(
        client,
        tool_name="create_file",
        payloads=[{"path": "report.txt", "content": "integration ok"}],
        final_text="Dry run complete.",
    )

    runner = AgentRunner(
        tools=[_build_create_file_tool()],
        options=AgentRunOptions(
            max_turns=1,
            verbose=False,
            dry_run=True,
            audit_log_path=audit_path,
            changes_log_path=changes_path,
        ),
        client=client,
    )

    result = runner.run("Create report.txt with 'integration ok'.")

    target = integration_workspace.path("report.txt")
    assert not target.exists()
    assert result.tool_events and result.tool_events[0].skipped is True
    assert "dry-run" in result.tool_events[0].result

    audit_lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert audit_lines, "expected audit log entry"
    audit_event = json.loads(audit_lines[0])
    assert audit_event["tool"] == "create_file"
    assert audit_event["skipped"] is True

    # Dry-run should not write change records
    assert not changes_path.exists() or not changes_path.read_text(encoding="utf-8").strip()


def test_parallel_read_tools_execute_concurrently(
    integration_workspace,
) -> None:
    """Two read-only tool calls within one turn should overlap in time."""

    call_timings: List[Tuple[float, float, str]] = []

    def build_slow_tool(name: str, delay: float) -> Tool:
        schema = {
            "type": "object",
            "properties": {
                "label": {"type": "string"},
            },
            "required": ["label"],
            "additionalProperties": False,
        }

        def handler(payload: Dict[str, str]) -> str:
            label = payload.get("label", "")
            start = time.perf_counter()
            time.sleep(delay)
            end = time.perf_counter()
            call_timings.append((start, end, label))
            return json.dumps({"ok": True, "label": label})

        return Tool(
            name=name,
            description="Deliberately slow read-only tool for concurrency checks.",
            input_schema=schema,
            fn=handler,
            capabilities={"read_fs"},
        )

    slow_tool = build_slow_tool("slow_reader", delay=0.25)

    client = MockAnthropic()
    queue_tool_turn(
        client,
        tool_name="slow_reader",
        payloads=[{"label": "first"}, {"label": "second"}],
        final_text="Finished both reads.",
    )

    runner = AgentRunner(
        tools=[slow_tool],
        options=AgentRunOptions(max_turns=2, verbose=False),
        client=client,
    )

    start = time.perf_counter()
    result = runner.run("Please run two slow_reader tasks in parallel.")
    total_duration = time.perf_counter() - start

    assert result.turns_used == 2
    assert len(call_timings) == 2, f"expected two tool calls, saw {call_timings}"

    sorted_calls = sorted(call_timings, key=lambda record: record[0])
    (first_start, first_end, _), (second_start, second_end, _) = sorted_calls

    assert second_start < first_end, "second tool call should overlap with first"
    assert total_duration < 0.4, "parallel execution should complete faster than serial sum"


def test_runner_cleans_up_after_mid_turn_failure(integration_workspace) -> None:
    """Mixed turn with a recoverable failure should leave state and telemetry consistent."""

    client = MockAnthropic()
    client.add_response_from_blocks(
        [
            text_block("Starting multi-tool turn."),
            tool_use_block(
                "create_file",
                {"path": "demo.txt", "content": "cleanup ok"},
                tool_use_id="call-success",
            ),
            tool_use_block(
                "flaky_tool",
                {"path": "demo.txt"},
                tool_use_id="call-failure",
            ),
            tool_use_block(
                "read_file",
                {"path": "demo.txt"},
                tool_use_id="call-read",
            ),
        ]
    )
    client.add_response_from_blocks([text_block("Turn complete despite failure.")])

    runner = AgentRunner(
        tools=[_build_create_file_tool(), _build_flaky_tool(), _build_read_file_tool()],
        options=AgentRunOptions(max_turns=2, verbose=False),
        client=client,
    )

    result = runner.run("Execute multiple tools with a mid-turn failure.")

    created = integration_workspace.path("demo.txt")
    assert created.exists()
    assert created.read_text(encoding="utf-8") == "cleanup ok"

    assert result.turns_used == 2
    assert result.stopped_reason == "completed"
    assert [event.tool_name for event in result.tool_events] == [
        "create_file",
        "flaky_tool",
        "read_file",
    ]

    failure_event = result.tool_events[1]
    assert failure_event.is_error is True
    assert failure_event.metadata.get("error_type") == "recoverable"

    read_event = result.tool_events[2]
    assert read_event.is_error is False
    assert "cleanup ok" in read_event.result

    assert runner.context is not None
    telemetry = runner.context.telemetry
    assert len(telemetry.tool_executions) == 3
    assert telemetry.tool_error_counts.get("flaky_tool") == 1
    assert any(not event.success for event in telemetry.tool_executions)

    assert result.turn_summaries and result.turn_summaries[0]["paths"] == ["demo.txt"]

    undo_ops = runner.undo_last_turn()
    assert undo_ops and any("removed" in op for op in undo_ops)
    assert not created.exists()


def test_parallel_mixed_read_write_serializes_write(integration_workspace) -> None:
    """Write tools should wait for in-flight read tools before executing."""

    timings: Dict[str, float] = {}

    def read_fn(arguments, tracker=None) -> str:
        timings["read_start"] = time.perf_counter()
        time.sleep(0.15)
        timings["read_end"] = time.perf_counter()
        return "read done"

    def write_fn(arguments, tracker=None) -> str:
        timings["write_start"] = time.perf_counter()
        time.sleep(0.05)
        timings["write_end"] = time.perf_counter()
        return "write done"

    read_tool = Tool(
        name="slow_read",
        description="",
        input_schema={"type": "object", "properties": {}},
        fn=read_fn,
        capabilities={"read_fs"},
    )
    write_tool = Tool(
        name="slow_write",
        description="",
        input_schema={"type": "object", "properties": {}},
        fn=write_fn,
        capabilities={"write_fs"},
    )

    client = MockAnthropic()
    client.add_response_from_blocks(
        [
            text_block("Starting mixed operations."),
            tool_use_block("slow_read", {}, tool_use_id="call-1"),
            tool_use_block("slow_write", {}, tool_use_id="call-2"),
        ]
    )
    client.add_response_from_blocks([text_block("All done.")])

    runner = AgentRunner(
        tools=[read_tool, write_tool],
        options=AgentRunOptions(max_turns=1, verbose=False),
        client=client,
    )

    runner.run("Run read then write")

    assert timings["write_start"] >= timings["read_end"]
    assert timings["write_start"] - timings["read_end"] < 0.1
