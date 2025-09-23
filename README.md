```text
+==============================================================+
|  ___ _   _ ____  _   _ ____ ___ _____  _    ____  _  __   __ |
| |_ _| \ | |  _ \| | | | __ )_ _|_   _|/ \  | __ )| | \ \ / / |
|  | ||  \| | | | | | | |  _ \| |  | | / _ \ |  _ \| |  \ V /  |
|  | || |\  | |_| | |_| | |_) | |  | |/ ___ \| |_) | |___| |   |
| |___|_| \_|____/ \___/|____/___| |_/_/   \_\____/|_____|_|   |
|                                                              |
|   ____ ___  ____  _____                                      |
|  / ___/ _ \|  _ \| ____|                                     |
| | |  | | | | | | |  _|                                       |
| | |__| |_| | |_| | |___                                      |
|  \____\___/|____/|_____|                                     |
|                                                              |
+==============================================================+
```

## Indubitably Code: Anthropic Agent Toolkit

A batteries-included playground for building with the Anthropic Messages API. Run a friendly
assistant ("Samus") in interactive or headless modes, wire in a rich tool belt, capture audit
trails, and even keep lightweight TODOs for your session.

### Highlights
- Minimal chat loop (`main.py`) when you just want raw model responses.
- Interactive agent (`run.py`) with colorized terminal UX, transcripts, and an extended toolset.
- Headless CLI (`indubitably-agent`) for CI/batch workflows with policy controls and JSON output.
- Comprehensive tools for filesystem edits, searches, shell execution, patch application, web lookups, and session planning.
- Context-aware prompt packing with automatic compaction, pins, and tool-output trimming.

### Context Management & Compaction
The agent now keeps a structured session history (`session/context.py`) backed by a token meter and compaction engine.
Key behaviours:
- Always preserve system guidance and the most recent user/assistant turns while summarising older conversation into goals, decisions, constraints, files, APIs, and TODOs.
- Auto-truncate oversized tool outputs using deterministic head/tail windows so critical excerpts stay in scope.
- Maintain a compact summary block that is reused across compaction passes to avoid token creep.
- Insert pinned snippets (coding standards, requirements, secrets placeholders) inside a dedicated budget so they persist across runs.

### Slash Commands & Status
Slash commands are available in the interactive TUI to inspect or tweak the session mid-run:
- `/status` – show token usage, last compaction, and active pins.
- `/compact [focus]` – force summarisation immediately.
- `/config set group.field=value` – adjust runtime settings such as `compaction.keep_last_turns`.
- `/pin add [--ttl=SECONDS] text` / `/unpin id` – manage compaction-resistant snippets.

### Configuration & Telemetry
Session defaults live in TOML via `session/settings.py`. By default we load `~/.agent/config.toml` (or the path from `INDUBITABLY_SESSION_CONFIG`) and honour sections such as:
```toml
[model]
name = "gpt-4.1"
context_tokens = 128000

[compaction]
auto = true
keep_last_turns = 4
target_tokens = 110000

[tools.limits]
max_tool_tokens = 4000
max_stdout_bytes = 131072
max_lines = 800
```
Telemetry counters (`session/telemetry.py`) record token usage, compaction events, drops, summariser invocations, pin sizes, and MCP fetches; call `/status` or inspect the session object to view them.

### Requirements
1. Python 3.13+
2. [`uv`](https://github.com/astral-sh/uv) package manager
3. An Anthropic API key (`ANTHROPIC_API_KEY`)

### Setup
```bash
uv sync
export ANTHROPIC_API_KEY=your_key_here
# optional overrides
export ANTHROPIC_MODEL=claude-3-7-sonnet-latest
export ANTHROPIC_MAX_TOKENS=2048
```

`uv sync` creates a `.venv/` alongside the project; activate it with `source .venv/bin/activate`
if you prefer using `python` directly instead of `uv run`.

---

## Entry Points

### Minimal non-agent loop
```bash
uv run python main.py
```
Type a message per line; press `Ctrl+C` to exit. The script replays the whole conversation each
turn and simply prints text blocks.

### Interactive agent with tools
```bash
uv run python run.py
# or: uv run python run.py --no-color --transcript logs/session.log
# enable tool traces: uv run python run.py --debug-tool-use
# export JSONL: uv run python run.py --tool-debug-log logs/tool-events.jsonl
```
Features:
- ASCII banner and prompt hints for quick onboarding.
- Configurable color output and optional transcript logging.
- Tool call tracing: see inputs and results inline (enable with `--debug-tool-use`).
- Optional JSONL export of tool calls for local audit trails.

### Headless CLI
```bash
uv run indubitably-agent --prompt "Summarize today's changes" --max-turns 6 \
  --allowed-tools read_file,list_files --audit-log logs/audit.jsonl \
  --debug-tool-use --tool-debug-log logs/tool-events.jsonl
```
Why use it:
- Deterministic runs in CI or Docker.
- Policy controls: allowlist/denylist tools, stop on errors, or dry-run to preview calls.
- Machine-readable `--json` summaries for pipelines.

---

## Toolbelt Cheat Sheet
The interactive and headless agents share the same default tools. Ask for them using natural
language; the agent translates your request into the schema below.

- **`read_file`** (filesystem read)
  - Slice files by byte ranges, line windows, or tail sections with configurable encoding/error handling.
  - Example prompt: `show lines 40-120 from src/service.py` or `tail the last 50 lines of logs/server.log`.
- **`list_files`** (filesystem inventory)
  - Recursive by default with depth limits, glob filters, ignore patterns, and sorting by name/mtime/size.
  - Example prompt: `list files under app/ matching **/*.tsx but skip node_modules`.
- **`grep`** (regex content search)
  - Walks the repo (respecting common ignore directories) and returns context, file lists, or counts.
  - Example prompt: `find usages of re.compile with 2 lines of context`.
- **`glob_file_search`** (fast filename lookup)
  - Glob for files (`**/` is auto-prepended) and get the newest matches first.
  - Example prompt: `locate all *.sql migrations`.
- **`codebase_search`** (heuristic semantic search)
  - Score files/snippets against a natural-language query, optionally scoped by directory or glob.
  - Example prompt: `find code related to oauth token refresh logic`.
- **`edit_file`** (text replacement & creation)
  - Replace exact strings or write new files when `old_str` is empty; errors if a match is missing.
  - Example prompt: `in config/settings.py replace DEBUG = True with DEBUG = False`.
- **`apply_patch`** (V4A diff application)
  - Apply structured Add/Update/Delete patches in one call; perfect for multi-line edits.
  - Example prompt: `apply this diff to docs/changelog.md` followed by the patch block.
- **`delete_file`** (safe removal)
  - Deletes files (not directories) and reports if the target was absent.
  - Example prompt: `delete the generated tmp/output.txt file`.
- **`run_terminal_cmd`** (guarded shell execution)
  - Runs commands in the configured shell; refuses obviously interactive binaries unless backgrounded.
  - Background jobs stream to `run_logs/job-*.out.log` & `.err.log`.
  - Example prompt: `run npm test -- --runInBand` or `run build.sh in the background`.
- **`aws_api_mcp`** (structured AWS CLI access)
  - Wraps the `aws` CLI with schema-validated inputs for read-focused operations.
  - Supports selecting service/operation, profile & region overrides, JSON-encoded parameters, and pager suppression.
  - Unsure about required flags? Ask the agent to run command help (e.g., `extra_args: ["help"]`) so it can read the AWS CLI usage before retrying.
  - Parameter names are normalized automatically, so `desiredCount: 0` or `logGroupName` work even if the CLI expects dashed flags.
  - Boolean parameters become toggle flags: `force: true` turns into `--force`; omit or set `false` to skip emitting the flag.
  - Example prompt: `fetch the last 50 events from CloudWatch log group /aws/lambda/payment-handler in us-west-2`.
- **`aws_billing_mcp`** (Cost Explorer insights)
  - Calls `aws ce` operations like get-cost-and-usage and forecasts with friendly timeframe/metric helpers.
  - Supports quick rollups (e.g., last_7_days by service) and advanced filters or groupings.
  - Example prompt: `show unblended cost by service for the last 30 days`.
- **`playwright_mcp`** (headless browser automation)
  - Opens pages with Playwright to collect screenshots, HTML content, or evaluated script results.
  - Handles navigation wait conditions, viewport tweaks, headers, base64 screenshot returns, and optional ASCII previews for terminal inspection.
  - Script inputs are auto-wrapped so you can paste snippets without worrying about arrow functions.
  - Example prompt: `open https://example.com and capture a full-page screenshot with an ascii preview`.
- **`todo_write`** (session TODOs)
  - Maintain `.session_todos.json`; merge or replace items with id/content/status fields.
  - Example prompt: `record todos for the session: update docs (pending), ship release (in_progress)`.
- **`web_search`** (best-effort SERP fetch)
  - Queries DuckDuckGo with Bing/Wikipedia fallbacks and returns titles + URLs (no scraping of result pages).
  - Example prompt: `search the web for django 5.1 release notes`.

---

## Asking for AWS Data in Plain Language
The `aws_api_mcp` tool is automatically available to the agent, so you can stay conversational and
let the model translate your intent into the structured AWS CLI call.

Steps:
1. Tell the agent what you need, plus any specifics (service, resource names, region, limits).
2. The agent will decide to invoke `aws_api_mcp` with the right parameters and return the CLI output.
3. Follow up with refinements (e.g., change `limit`, add time filters) the same way you would in a chat.

Example dialogue:
```text
You ▸ Pull the last 25 CloudWatch log events for the Lambda payment-handler in us-west-2.
Samus ▸ (calls aws_api_mcp → `logs filter-log-events --log-group-name /aws/lambda/payment-handler --limit 25 --region us-west-2`)
Samus ▸ (returns pretty-printed JSON log events)
```

To customize further, mention parameters like `start-time`, specific log stream names, or even switch
services (for example, "Describe the current Lambda configuration" or "List the DynamoDB tables in
production"). The agent routes each request through the tool without requiring you to remember the
AWS CLI syntax.

If a request fails because required CLI flags are missing, follow up with something like
"Check the help for that CLI command". The agent can rerun the tool with `extra_args` set to `help`
or even call a service-level help operation (`service=ecs, operation=help`) to inspect the AWS CLI
usage text before adjusting the parameters.

When iterating on AWS calls, watch for model rate limits. The agent automatically backs off and
retries up to five times on Anthropic 429 responses, but shortening prompts, lowering `--max-turns`,
or pausing between retries will help avoid hitting your per-minute budget.

### Optional dependencies
- Playwright tooling (`playwright_mcp`) requires `uv add playwright` followed by `uv run playwright install` to provision browser binaries.
- ASCII previews for Playwright screenshots require `uv add pillow`. Use both `return_screenshot_base64: true` and `ascii_preview: true` when you want the raw bytes and a terminal-friendly view in one call.

For billing insights, stay conversational as well:
```text
You ▸ How much did we spend by service in the last month?
Samus ▸ (calls aws_billing_mcp → `ce get-cost-and-usage --time-period Start=2024-08-01,End=2024-09-01 --metrics UnblendedCost --group-by ...`)
Samus ▸ (summarizes the cost by service)
```

Feel free to iterate on timeframe (`last_7_days`, `month_to_date`), granularity (`DAILY`, `MONTHLY`),
or add dimensions/tag keys to `group_by` just by describing what you need.

---

## Headless Runs in Depth

### Common flag combinations
- `--max-turns N` – cap Anthropic responses (default 8 turns).
- `--exit-on-tool-error` – stop immediately if any tool reports an error.
- `--dry-run` – skip execution and return `tool_result` stubs noting the skip.
- `--allowed-tools` / `--blocked-tools` – comma-separated allowlist/denylist.
- `--audit-log path.jsonl` – append every tool invocation as JSON.
- `--debug-tool-use` / `--no-debug-tool-use` – toggle verbose stderr tracing of tool calls (default off).
- `--tool-debug-log path.jsonl` – when debugging is enabled, append structured tool call events.
- `--changes-log path.jsonl` – track filesystem writes (successful or attempted) for auditing.
- `--json` – emit a structured summary; `--verbose` adds stderr progress updates.

Example (previewing a run for CI):
```bash
uv run indubitably-agent --prompt-file prompts/daily.md \
  --config examples/headless-runner.toml \
  --dry-run --json > run-plan.json
```
Dry runs still record planned tool calls in the audit log and mark them as `skipped`.

### Runner config files
Store defaults in TOML and override selectively on the CLI:
```toml
# examples/headless-runner.toml
[runner]
max_turns = 6
exit_on_tool_error = true
dry_run = false
allowed_tools = ["read_file", "grep", "codebase_search", "todo_write"]
audit_log = "logs/audit.jsonl"
changes_log = "logs/changes.jsonl"
# enable tool tracing for headless runs
debug_tool_use = true
tool_debug_log = "logs/tool-events.jsonl"
```
Relative paths resolve from the config file location, making it easy to mount a directory in Docker
or CI and collect artifacts.

---

## Logs, Artifacts, and State
- **Transcripts**: `run.py --transcript path.log` appends the banner, prompts, tool calls, and responses.
- **Audit log**: each tool event includes turn number, input payload, result string, and paths touched.
- **Tool debug log**: turn-indexed tool events captured when `--debug-tool-use` is active.
- **Change log**: when writing tools succeed (or even attempt writes), their target paths are recorded.
- **Background commands**: look under `run_logs/` for stdout/stderr captured by `run_terminal_cmd`.
- **Session TODOs**: `.session_todos.json` keeps the most recent list written by `todo_write` with timestamps.

### Testing
Run `pytest -q` to execute the full suite, including new coverage for session compaction, slash commands, and CLI wiring.

---

## Docker usage
```bash
docker build -t indubitably-agent .
docker run --rm -e ANTHROPIC_API_KEY=sk-... \
  -v "$PWD/logs:/out" indubitably-agent \
  --config examples/headless-runner.toml \
  --prompt "Summarize latest commits" \
  --audit-log /out/audit.jsonl
```
The image uses `uv sync` during build and exposes the `indubitably-agent` entrypoint. Mount a volume
for logs or change outputs as needed.

---

## Try it out
```
what do you see in this directory?
search the codebase for "AgentRunner"
apply this patch to README.md
run pytest -q
log a todo: add usage examples to docs
search the web for python 3.13.1 release notes
```
The agent will chain tool calls, stream results, and provide a concise wrap-up when it can. If you
need hallucination-free runs, favor `--dry-run` to inspect planned actions before letting Samus loose.

Happy hacking!

---

## License

This project is licensed under the [Apache License 2.0](LICENSE).

