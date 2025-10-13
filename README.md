## Indubitably Code

Our local agent harness for rapid tool experimentation, policy validation, and workflow
automation. This repository packages a production-inspired conversation loop with a fully managed
toolbelt, approval policies, telemetry, and integration-test scaffolding so you can iterate on
autonomous coding flows with confidence.

---

### What’s Inside

- **Multi-mode agents** – run the lightweight `main.py` loop, the interactive TUI (`run.py`), or
  the CI-friendly headless runner (`indubitably-agent`).
- **Production-grade tooling** – filesystem edits, semantic searches, guarded shell execution,
  MCP client pooling, and AWS helpers are all wired in by default.
- **Session intelligence** – automatic prompt compaction, pin management, deterministic output
  truncation, and TODO tracking keep context tidy.
- **Safety rails** – approval policies (`never`, `on_request`, `on_write`, `always`), sandboxed
  command filters, and structured audit logs make review straightforward.
- **Observability** – OpenTelemetry-style metrics, JSONL audit trails, change summaries, and tool
  debug logs expose every turn.

---

## Quick Start

### Requirements

1. Python 3.13+
2. [`uv`](https://github.com/astral-sh/uv) package manager
3. Anthropic API key (`ANTHROPIC_API_KEY`)

### Install

```bash
uv sync
export ANTHROPIC_API_KEY=sk-ant-your-key
# Optional model overrides
export ANTHROPIC_MODEL=claude-sonnet-4.5
export ANTHROPIC_MAX_TOKENS=4096
```

`uv sync` creates a local `.venv/`; activate it if you prefer `python` over `uv run`:

```bash
source .venv/bin/activate
```

---

## Run Modes

### Minimal Loop

```bash
uv run python main.py
```

Single-threaded prompt/response driver ideal for quick API checks.

### Interactive Agent (TUI)

```bash
uv run python run.py \
  --no-color \
  --transcript logs/session.log \
  --debug-tool-use \
  --tool-debug-log logs/tool-events.jsonl
```

Features: session banner, slash commands (`/status`, `/compact`, `/pin`), colored output, optional
transcripts, and live tool tracing.

### Headless Runner

```bash
uv run indubitably-agent \
  --prompt "Summarize the new telemetry tests" \
  --max-turns 6 \
  --allowed-tools read_file,list_files \
  --audit-log logs/audit.jsonl \
  --json
```

Automates conversations for CI/CD: deterministic prompts, tool allow/deny lists, dry-run mode, and
machine-readable summaries.

---

## Toolbelt Overview

| Tool | Capabilities | Highlights |
| --- | --- | --- |
| `read_file` | `read_fs` | Byte and line windows, encoding controls, safe tailing |
| `list_files` | `read_fs` | Recursive inventory with glob filters and ignore patterns |
| `grep` | `read_fs` | Regex search with context lines and match counts |
| `glob_file_search` | `read_fs` | Rapid filename lookups with prioritised results |
| `codebase_search` | `read_fs` | Semantic query scoring across the repo |
| `edit_file` | `write_fs` | Exact string replacement or file creation |
| `apply_patch` | `write_fs` | Structured diff application with conflict detection |
| `delete_file` / `rename_file` / `create_file` | `write_fs` | Safe mutations with diff tracking |
| `run_terminal_cmd` | `exec_shell` | Foreground/background execution, timeout enforcement, truncation metadata |
| `aws_api_mcp`, `aws_billing_mcp`, `playwright_mcp` | `exec_shell` | Managed MCP clients with pooled discovery |
| `todo_write`, `template_block` | `write_fs` | Session planning and templating utilities |

More tools live under `tools/`; the registry wiring happens in `run.py` and `agent_runner.py`.

---

## Policies & Approvals

Execution settings live in `session/settings.py` (TOML-backed). Approval policy options:

| Policy | Behaviour |
| --- | --- |
| `never` | Execute immediately, record skip metadata only on errors |
| `on_request` | Agent may call `request_approval` manually |
| `on_write` | All tools with `write_fs` capabilities require approval; metadata now includes `approval_required`, `approval_granted`, `approval_paths` |
| `always` | Every tool invocation requires approval |

During headless runs, denied approvals surface as skipped tool events with audit traces. Sandbox
settings (`execution.sandbox`, `execution.allowed_paths`, `execution.blocked_commands`) layer on top
to restrict shell commands and filesystem writes.

---

## Telemetry, Audits & Truncation

- **Audit logging** – enable via `AgentRunOptions.audit_log_path` (headless) or `--tool-debug-log`.
- **Change tracking** – per-turn diffs and undo operations captured in `AgentRunResult.turn_summaries`
  plus optional `changes.jsonl`.
- **Telemetry** – `SessionTelemetry` records tool timings, success/failure counts, truncation flags,
  policy prompts, and MCP fetch metrics. Use `TelemetrySink` during tests to assert exports.
- **Output truncation** – deterministic head/tail windows keep responses within
  `MODEL_FORMAT_MAX_BYTES`. Metadata now includes `truncated` so audits and telemetry can flag
  shortened outputs.

---

## MCP Integration

The harness can connect to Model Context Protocol servers:

- **Stubbed pooling**: `tests/integration/test_mcp_pooling_integration.py` validates discovery,
  tool registration, and client recycling.
- **Live smoke** (optional): set `CHROME_MCP_SMOKE=1` to exercise the Chrome DevTools server via
  Playwright. Slow tests are guarded with `pytest -m mcp_live` markers.

---

## Testing & Quality Gates

### Core Commands

```bash
# Unit & functional tests
uv run pytest

# Integration focus (policies, runner, truncation)
uv run pytest \
  tests/integration/test_policies_integration.py \
  tests/integration/test_agent_runner_integration.py \
  tests/integration/test_output_truncation_integration.py

# Lint/type checks (if configured)
uv run ruff check
uv run mypy
```

### Integration Coverage Highlights

- **Policies** – approval combos, sandbox enforcement, and on-write audit metadata (`tests/integration/test_policies_integration.py`).
- **Runner cleanup** – mid-turn failure handling, telemetry consistency, and undo flow
  (`tests/integration/test_agent_runner_integration.py`).
- **Truncation telemetry** – head/tail formatting and `truncated` flags across foreground and
  background shell commands.
- **MCP pooling** – discovery, registration, and client eviction under error conditions.

See `integration-testing.md` for the full roadmap and remaining TODO suites (Ctrl+C handling,
Seatbelt/Landlock approvals, MCP live smoke).

---

## Configuration Reference

Default settings load from `INDUBITABLY_SESSION_CONFIG` or `~/.agent/config.toml`. Example:

```toml
[model]
name = "claude-sonnet-4.5"
context_tokens = 200000

[compaction]
auto = true
keep_last_turns = 4
target_tokens = 180000

[execution]
approval = "on_write"
sandbox = "restricted"
timeout_seconds = 120

[tools.limits]
max_tool_tokens = 4000
max_stdout_bytes = 131072
max_lines = 800
```

Disable auto-compaction or tweak truncation limits by adjusting these fields at runtime via
`/config set execution.timeout_seconds=30`, etc.

---

## Project Map

| Path | Purpose |
| --- | --- |
| `agent.py` | Interactive agent loop powering the TUI |
| `agent_runner.py` | Headless runner with policy enforcement and auditing |
| `session/` | Context, compaction, telemetry, settings, and history management |
| `tools/` | Tool handlers, schemas, MCP integration, and runtime plumbing |
| `tests/` | Unit and integration suites (see `integration-testing.md` for roadmap) |
| `docs/` | Architecture and testing deep dives |

---

## Contributing

1. Sync dependencies with `uv sync`.
2. Create a feature branch and enable approvals/tests relevant to your change.
3. Run the focused pytest suites plus any linting/type checks.
4. Update documentation (`integration-testing.md`, `docs/testing.md`, README) when behaviour shifts.
5. Submit a PR with audit logs or telemetry evidence when modifying policies or truncation logic.

Questions or ideas? Open an issue or start a discussion so we can evolve the harness together.
