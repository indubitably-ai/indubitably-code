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


