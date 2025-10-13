# Integration Testing Plan

This document outlines the integration-test suites we need in order to match the expectations from
`architecture-summary.md` (tool layering, telemetry, MCP pooling) and `test-architecture-summary.md`
(async-first harnesses, deterministic mocks, parallelism verification). The goal is to cover all
critical behaviors that unit tests cannot validate in isolation—especially asynchronous tool flows
and external MCP interactions.

## 1. Environment & Harness Prerequisites

- **Python tooling**: `uv`-managed virtualenv, `pytest`, `pytest-asyncio` (for native async tests),
  and the in-repo `tests/mocking` Anthropic stubs.
- **CLI driver**: helper to spawn the REPL or headless runner in-process (prefer using `AgentRunner`
  plus the mock anthropic client rather than shelling out).
- **MCP fixtures**:
  - Stub stdio server powered by the `mcp` Python client for fast deterministic tests.
  - Optional smoke fixture that boots the Chrome DevTools MCP (gated behind an env flag and marked
    `slow` so it only runs when Chrome/npx are available).
- **File-system sandbox**: temporary workspace per test to isolate edits (as described in
  `test-architecture-summary.md` → isolated envs via `TempDir`/fixtures).
- **Timing helpers**: re-use the barrier/timing utilities from `tests/utils/timing.py` for parallel
  assertions.

## 2. Shared Test Fixtures

| Fixture | Purpose |
| ------- | ------- |
| `mock_anthropic` | Deterministic Anthropic responses, collects request payloads. |
| `tool_registry_factory` | Builds tool router/runtime with default tools and dependency injection for mocks. |
| `temp_repo` | Temporary repo-like directory with helper to seed files. |
| `mcp_stub_server` | Async context manager that uses `connect_stdio_server` to launch a stub MCP server returning scripted tool lists/results. |
| `repl_driver` | Utility that feeds input/output against `run_agent` or `AgentRunner`; handles ESC interrupts and transcripts. |
| `otel_export_sink` | Captures OTEL exporter payloads for telemetry assertions. |

## 3. Test Suites

### 3.1 CLI & REPL Baseline
- **Goal**: ensure the interactive agent boots, prints banners, and handles simple conversations.
- **Scenarios**:
  1. Startup with no MCP servers → expect banner, prompt, `/status` output.
  2. `/compact`, `/pin`, `/status` interactions mutate session state and print expected text.
  3. Graceful shutdown on EOF / Ctrl+C (listener disarmed, context closed).
- **Verification**: use `repl_driver` to feed commands; assert transcripts, context counters, and
  that `ContextSession.close` was awaited.
- **Current coverage**: `tests/integration/test_cli_repl_integration.py` exercises banner rendering, user prompt, tool execution, `/status`, `/pin`, `/compact`, and `tests/integration/test_repl_interrupt_integration.py` verifies ESC interrupts. Ctrl+C signal handling is still TODO.

### 3.2 Headless Runner Smoke
- **Goal**: validate `AgentRunner` end-to-end (tool routing, result aggregation, audit logs).
- **Scenarios**:
  1. Basic write tool updates file, audit/changes logs populated.
  2. Dry-run leaves audit entry marked `skipped`, file unchanged.
  3. Error path stops the runner when `exit_on_tool_error=True`.
- **Artifacts**: inspect `AgentRunResult`, audit JSONL, and telemetry counters.
- **Current coverage**: `tests/integration/test_agent_runner_integration.py` verifies a write tool mutating the workspace, confirms parallel read-only execution, covers dry-run audit logging, and asserts state/telemetry cleanup after a mid-turn tool failure. Handling of fatal tool errors and `exit_on_tool_error` remains TODO.

### 3.3 Tool Execution & Validation
- Cover each built-in tool category with integration-level assertions:
  - `read_file`, `list_files`, `glob`, `grep` → confirm outputs and tracer logs.
  - `run_terminal_cmd` foreground/background flows (ensure log files, timeout caps).
  - `apply_patch` + diff tracker integration.
  - `web_search` mock that simulates HTTP responses.
- Current coverage: `tests/integration/test_tool_execution_integration.py` exercises list/read/grep flows, `apply_patch`, background shell execution, and foreground timeout enforcement.
- Missing pieces: glob + list combinations, `web_search` mocked responses, structured validation errors (pydantic), and tool-result dedupe/metadata assertions.
- Include structured argument validation (pydantic errors) and tool-result dedupe checks.

### 3.4 Asynchronous & Parallel Execution
- Use timing barriers to verify parallelizable tools truly run concurrently (`test-architecture-summary.md` pattern).
- Tests:
  1. Two read-only tools finish ~same time (parallel).
  2. Mix of read + write falls back to serial ordering.
  3. Interrupt handling (`ESC`) cancels pending tasks and logs a manual interrupt.
- **Current coverage**: `tests/integration/test_agent_runner_integration.py` covers read/read overlap and read→write serialization. Manual interrupt handling is still TODO.

### 3.5 Policy & Sandbox Integration
- With approval policy combos (`never`, `on_write`, `always`) ensure agent prompts for approval, denies if callback returns False.
- Sandbox enforcement: strict mode blocks disallowed commands; restricted mode allows safe commands but blocks writes outside allowed paths.
- Confirm `ToolOutput` metadata contains `error_type` and audit logs show policy reason.
- Current coverage: `tests/integration/test_policies_integration.py` verifies `run_terminal_cmd` approval gating, command blocking, sandbox path enforcement, and `on_write` write-tool approvals with audit metadata.
- Missing pieces: Seatbelt/Landlock platform hooks, explicit decline-path assertions, and telemetry counters for policy prompts.

### 3.6 MCP Integration & Pooling
- **Stubbed MCP**: using `mcp_stub_server` verify:
  - Registrations from `[mcp.definitions]` are pooled, `list_tools` response adds specs to registry/router.
  - `call_tool` success path returns stubbed result, telemetry `mcp_fetches` increments.
  - Error path triggers `mark_mcp_client_unhealthy` and subsequent call recreates client.
- **Chrome DevTools smoke (optional/slow)**:
  - Gated by env `CHROME_MCP_SMOKE=1`.
  - Launch real server via `npx`, call simple tool (`list_pages`), assert non-empty content.
- **Current coverage**: `tests/integration/test_mcp_pooling_integration.py` exercises stubbed MCP discovery, registration, and pooled invocations. Error recovery and live smoke tests remain TODO.

### 3.7 Telemetry & OTEL Export
- Record real tool invocations and ensure `SessionTelemetry` counters update (`tokens_used`, `mcp_fetches`, etc.).
- Use `TelemetrySink` (see `tests/integration/helpers/telemetry.py`) to assert OTEL payload contains resource attributes and correct tool metrics.
- Current coverage: `tests/integration/test_telemetry_integration.py` validates telemetry events, OTEL export, and sink capture during a `read_file` turn; truncation flags are covered via `tests/integration/test_output_truncation_integration.py`.
- Missing pieces: telemetry for error/fatal tool events, parallel batch metrics, policy/Sandbox counters, and MCP fetch failures.

### 3.8 Error Handling & Recovery
- Simulate `RateLimitError` from the anthropic client: runner retries with backoff, logs message.
- Fatal tool errors propagate `fatal_tool_error` stop reason and stop further execution.
- Ensure `AgentRunner.close()` tears down pooled resources even after exceptions.
- **Current coverage**: `tests/integration/test_error_recovery_integration.py` asserts fatal tool behavior with `exit_on_tool_error`.

### 3.9 Turn Diff Tracking & Undo
- Verify `TurnDiffTracker` collects reads/writes, populates change summaries, and enables `undo_last_turn` to restore prior content.
- Cover edit/create/delete workflows, including conflicting edits within a turn.
- Exercise `AgentRunResult.turn_summaries` and changes log emission for review flows.
- **Current coverage**: `tests/integration/test_turn_diff_integration.py` verifies edit tracking and undo via `apply_patch`.

### 3.10 Output Truncation & Large Payloads
- Execute commands that exceed truncation thresholds (e.g., long `run_terminal_cmd` output) and assert head/tail formatting plus metadata (`timed_out`, `omitted`, `truncated`).
- Ensure truncated outputs still stream fully to the user transcript while the model receives the compact form.
- Validate telemetry/log entries include truncation markers for both truncated and non-truncated outputs.
- **Current coverage**: `tests/integration/test_output_truncation_integration.py` exercises foreground truncation and telemetry metadata; background execution telemetry lives in `tests/integration/test_tool_execution_integration.py`.
- Missing pieces: background truncation scenarios (e.g., large detached logs) and REPL streaming assertions.

### 3.11 Context Compaction & Pins
- Force compaction by driving history over token thresholds, assert summaries are produced, pins preserved, and `/compact` reporting matches architecture expectations.
- Cover `/pin add`, `/pin remove`, TTL expiry, and status reporting.
- **Current coverage**: `tests/integration/test_compaction_integration.py` covers `/pin add` and `/compact` flows via the REPL driver.

### 3.12 Load / Chaos Hooks (follow-up)
- Not part of CI by default; document scripts to:
  - Spawn multiple parallel turns with pooled MCP server (stress TTL eviction and health-check logic).
  - Run long-running shell commands to validate timeout enforcement.
  - Simulate MCP server crash mid-turn and ensure pool evicts client and surfaces error.

## 4. Implementation Notes
- Prefer `pytest.mark.asyncio` (or equivalent) for native async tests; avoid `asyncio.run` inside tests when a loop is already running.
- Use named markers: `slow`, `mcp_live` for optional tests; configure CI matrix to skip them.
- Combine reusable helper modules under `tests/integration/helpers/` for context setup, approval mocks, telemetry sinks.
- When comparing timing for parallel tests, use the tolerances recommended in
  `test-architecture-summary.md` (e.g., serial duration >= n × single-task duration).
- Log captured Anthropic requests to assert tool definitions are included and MCP tools appear once.

## 5. Tracking & Coverage Matrix

| Suite | Key Files | Status |
|-------|-----------|--------|
| CLI/REPL smoke | `tests/integration/test_cli_repl_integration.py` | partial coverage (status/pin/compact); TODO Ctrl+C handling |
| Headless Agent | `tests/integration/test_agent_runner_integration.py` | partial coverage (write, dry-run, parallel, mid-turn failure cleanup); TODO fatal tool errors, `exit_on_tool_error` |
| Tool categories | `tests/integration/test_tool_execution_integration.py`, `tests/integration/test_web_search_integration.py` | partial coverage (read/list/grep/apply_patch/glob/background & timeout/web search); TODO validation errors |
| Parallel execution | `tests/integration/test_agent_runner_integration.py` | partial coverage (read/read overlap + read→write serialization); TODO interrupt handling |
| Policy enforcement | `tests/integration/test_policies_integration.py` | partial coverage (approval always/on_write, blocked commands, sandbox paths); TODO Seatbelt/Landlock hooks, declined approvals, telemetry counters |
| MCP pooling | `tests/integration/test_mcp_pooling_integration.py` | partial coverage (stubbed discovery/calls); TODO error handling, live smoke |
| Telemetry export | `tests/integration/test_telemetry_integration.py` | partial coverage (success + blocked-command error + truncation flags); TODO fatal tool metrics, parallel batch counters, policy prompts |
| Error/Recovery | `tests/integration/test_error_recovery_integration.py`, `tests/integration/test_rate_limit_integration.py` | partial coverage (fatal tool stop + rate-limit retries); TODO cleanup on exceptions |
| Turn diff & undo | `tests/integration/test_turn_diff_integration.py` | partial coverage (apply_patch + undo); TODO multi-file, conflict detection |
| Output truncation | `tests/integration/test_output_truncation_integration.py` | partial coverage (foreground truncation + telemetry markers); TODO background truncation cases, REPL streaming validation |
| Compaction & pins | `tests/integration/test_compaction_integration.py` | partial coverage (pin add/compact); TODO TTL expiry, token-threshold compaction |
| Live MCP smoke | `tests/integration/test_mcp_live.py` (slow) | optional |

## 6. Next Steps
1. **REPL resilience**: extend `test_repl_interrupt_integration.py` (or new suite) to simulate SIGINT/Ctrl+C, asserting graceful shutdown, session cleanup, and telemetry counters.
2. **Policy depth**: add Seatbelt/Landlock approval fixtures, cover user-declined approvals, and ensure policy prompts increment telemetry counters.
3. **Telemetry completeness**: capture fatal tool metrics, parallel batch stats, and policy prompt counters across `test_telemetry_integration.py` and headless-runner suites.
4. **Truncation edge cases**: exercise background commands that exceed truncation thresholds and verify REPL transcript handling alongside telemetry flags.
5. **MCP live smoke**: stand up gated tests against a real MCP server (Chrome DevTools) covering discovery, retries, and pooled client recycling.
6. **Documentation & markers**: update `docs/testing.md` with marker guidance (`slow`, `mcp_live`) and command recipes for optional suites.
