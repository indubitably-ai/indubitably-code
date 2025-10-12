# Migration Guide: From Legacy Tools to the Codex-Style Harness

This guide summarizes the completed migration work that brings the indubitably agent in line with
Anthropic's codex-rs architecture. It highlights practical operational steps, the new policy system,
and how the testing story maps onto the patterns called out in `architecture-summary.md` and
`test-architecture-summary.md`.

---

## 1. Execution Policies & Configuration

Phase 9 introduced a dedicated `policies.py` module and extended `SessionSettings` with an
`execution` block. These values can be supplied via `INDUBITABLY_SESSION_CONFIG`, the default config
search paths, or updated in-session through `/config` commands.

| Setting              | Purpose                                                                              | Defaults              |
|----------------------|--------------------------------------------------------------------------------------|-----------------------|
| `sandbox`            | Controls the shell allowlist (`none`, `restricted`, `strict`).                       | `restricted`          |
| `approval`           | Determines when user consent is required (never/on_request/on_write/always).         | `on_request`          |
| `allowed_paths`      | Optional tuple of write-safe directories.                                           | `()` (no restriction) |
| `blocked_commands`   | Optional tuple of disallowed substrings for commands.                               | `()`                  |
| `timeout_seconds`    | Hard cap for foreground shell calls; coerces tool-provided `timeout` values.        | `None` (no override)  |

Every `ContextSession` now materializes an `ExecutionContext` from these settings, and the new
`shell` handler applies the policy checks before delegating to `run_terminal_cmd`.

**Quick Start**

```toml
[execution]
sandbox = "restricted"
approval = "on_write"
allowed_paths = ["./", "~/notes"]
blocked_commands = ["rm -rf", "shutdown"]
timeout_seconds = 180.0
```

---

## 2. Shell Handler Enforcement Flow

The `ShellHandler` wraps the legacy `run_terminal_cmd` tool, satisfying the architecture summary's
requirement for layered safety gates. Execution steps:

1. Validate JSON arguments using the existing Pydantic schema.
2. Apply sandbox/command allowlist rules and timeout coercion.
3. Request approval via `turn_context.request_approval` when policies demand it.
4. Delegate to the synchronous tool implementation via the shared executor bridge.
5. Return structured `ToolOutput` messages for telemetry and the model.

Missing approval hooks return a policy denial, preventing the model from accidentally bypassing
human oversight.

---

## 3. Testing Coverage & Strategy

The test suite now mirrors the guidance in `test-architecture-summary.md`:

- **Unit tests** (e.g., `tests/test_policies.py`) assert schema/policy behavior in isolation.
- **Integration tests** (`tests/test_shell_handler.py`, `tests/tools/test_legacy.py`) run through the
  handler stack, checking blocked commands, approval gates, and timeout coercion.
- **Harness tests** (`tests/test_agent_runner.py`, `tests/test_harness_agent.py`) ensure the runtime
  wiring respects approvals, produces telemetry, and writes audit artifacts.
- **Parallelism & runtime tests** remain green (`tests/test_tool_timing.py`, `tests/tools/test_parallel.py`).

CI entry point: `uv run pytest` (passes 205 tests, 2 skips at time of writing). Running the full
suite validates registry wiring, MCP integration, and policy enforcement.

---

## 4. Operational Checklist

Before enabling the new harness in production environments:

1. **Set policy defaults** that match your safety posture (strict sandbox, approval on write, etc.).
2. **Provision approval callbacks** in headless contexts so policy prompts can reach operators.
3. **Audit telemetry sinks** (Phase 6/7 work) to ensure policy denials and command executions are
   tracked.
4. **Re-run the test suite** on target platforms (`uv run pytest`).
5. **Update user documentation**: point contributors to this guide and the policy section in the README.

---

## 5. Forward-Looking Hardening

The architecture summary identifies additional production enhancements that can follow this migration:

- Build a shared MCP client pool for long-lived server connections.
- Stream telemetry via OTEL exporters for fleet-wide observability.
- Schedule load and chaos tests that exercise parallel execution and fault recovery paths.

These items are optional for the migration milestone but valuable for post-launch hardening.

---

## 6. Reference Documents

- `architecture-summary.md` — deep dive into component responsibilities and production concerns.
- `test-architecture-summary.md` — the canonical testing blueprint mirrored by our suite.
- `migration.md` — phase-by-phase plan, now fully checked off through Phase 10.

With the policy infrastructure, documentation, and tests in place, the migration plan is complete and
aligned with the target codex-rs architecture. Continue iterating on telemetry, MCP pooling, and load
validation as you transition from migration to operational hardening.

## 7. MCP Client Pooling

Populate `[mcp.definitions]` entries in your session TOML to launch real MCP servers (for example, the
Chrome DevTools MCP from this repo). The harness spins each server up via `connect_stdio_server`, feeds
the handles into `MCPClientPool`, and keeps them warm for future tool calls. Example definition:

```toml
[mcp]
  enable = true
  [[mcp.definitions]]
  name = "chrome-devtools"
  command = "npx"
  args = ["-y", "chrome-devtools-mcp@latest"]
  ttl_seconds = 300
```

During runtime, `ContextSession` pools the connections, `AgentRunner` auto-discovers the tools exposed
by each server, and you can fetch a client on demand via `await context.get_mcp_client("chrome-devtools")`.
Call `await context.close()` during teardown so pooled clients are shut down neatly.

## 8. Telemetry Export

`SessionTelemetry.flush_to_otel` streams tool execution events to the lightweight `OtelExporter`, which
writes OTLP-style JSON payloads to a file, stream, or in-memory buffer. Hook the exporter into your
observability pipeline (or wrap it with the OpenTelemetry SDK) to mirror codex-rs’s distributed
telemetry story.

```
telemetry.record_tool_execution(...)
exporter = OtelExporter(path=Path("/var/log/indubitably-tool-events.jsonl"))
telemetry.flush_to_otel(exporter)
```

## 9. Load & Chaos Testing Hooks

Use the new MCP pool and telemetry exporter in staging load tests to simulate sustained traffic. The
pool prevents per-call connection spikes, while telemetry payloads give quick visibility into tail
latency and failure modes. Combine them with the existing parallel execution tests for a holistic
stress harness.
