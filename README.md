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

## Indubitably Code: Anthropic Agent + Minimal Chat (Python)

This repo implements two entry points using the Anthropic Python SDK:

- Minimal non-agent chat loop (`main.py`)
- Tool-enabled agent (`run.py`) with `read_file`, `list_files`, and `edit_file` tools

Model: `claude-3-7-sonnet-latest`.

### Prerequisites

1) Python 3.13+
2) Install `uv` (fast Python package manager)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
# or: pipx install uv
```

3) Sync environment (creates `.venv` by default) and export your API key

```bash
uv sync
export ANTHROPIC_API_KEY=your_key_here
```

### Non-agent chat (terminal loop)

```bash
uv run python main.py
# type messages; press Ctrl+C to exit
```

What it does:
- Maintains a local `conversation` list and sends it each turn
- Prints assistant text blocks

### Agent chat with tools

Tools included:
- `read_file(path)`: returns file contents
- `list_files(path?)`: lists files/dirs ("/" suffix for dirs), recursive from `path` or `.`
- `edit_file(path, old_str, new_str)`: replace text; if file missing and `old_str==""`, creates file with `new_str`

Run the agent:

```bash
uv run python run.py
```

Options for the interactive runner:

- `--no-color` disables ANSI color output (useful when piping or on limited terminals)
- `--transcript path.log` appends each turn and tool action to a log file for later review

### Headless agent CLI

Use the CLI when you need non-interactive runs (CI, Docker, scripting):

```bash
uv run indubitably-agent --prompt "Summarize today's changes" --max-turns 6 \
  --allowed-tools read_file,list_files --audit-log logs/audit.jsonl
```

Key switches:

- `--prompt` / `--prompt-file`: initial user message (stdin supported when omitted)
- `--allowed-tools` / `--blocked-tools`: whitelist or blacklist individual tools
- `--dry-run`: plan the tool calls without executing them
- `--exit-on-tool-error`: fail fast if any tool reports an error
- `--audit-log` / `--changes-log`: persist JSONL audit records and touched files
- `--json`: emit a machine-readable run summary for pipelines

#### Config-driven runs

Provide defaults in a TOML file and override selectively via CLI:

```toml
# examples/headless-runner.toml
[runner]
max_turns = 6
exit_on_tool_error = true
allowed_tools = ["read_file", "list_files", "grep"]
audit_log = "logs/audit.jsonl"
changes_log = "logs/changes.jsonl"
```

Run with:

```bash
uv run indubitably-agent --config examples/headless-runner.toml --prompt-file prompt.md
```

Relative log paths resolve against the config file location so you can mount a bind volume in Docker/CI and collect artifacts.

#### Docker usage

Build a container with the bundled `Dockerfile` and run the headless agent in pipelines:

```bash
docker build -t indubitably-agent .
docker run --rm -e ANTHROPIC_API_KEY=sk-... \
  -v "$PWD/logs:/out" indubitably-agent \
  --config examples/headless-runner.toml --audit-log /out/audit.jsonl \
  --prompt "Summarize latest commits"
```

The image installs dependencies with `uv sync` and exposes the `indubitably-agent` entrypoint, making it easy to script non-interactive tasks.

Try these:

```text
what do you see in this directory?
what's in main.py?
hey claude, create fizzbuzz.js that I can run with Node.js and that has fizzbuzz in it and executes it
please edit fizzbuzz.js so that it only prints until 15
```

How it works:
- The model may emit `tool_use` blocks.
- The app dispatches locally, returns `tool_result` blocks as a user message, and continues the loop.

### Notes

- You can swap model id by editing `model=` in `main.py` and `agent.py`.
- `uv sync` will create and manage a local virtual environment and install dependencies from `pyproject.toml`/`uv.lock`.
- To activate the virtualenv for the current shell (optional):

```bash
source .venv/bin/activate
# then run:
python main.py
python run.py
```
